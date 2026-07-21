from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

CONTROL_MARKER_RE = re.compile(r"__(?:ASK|SKIP)__|{{[^{}]+}}|%\([^)]+\)s")
MIN_MEANINGFUL_LETTER_LEN = 20


def bot_base() -> Path:
    return Path(os.environ.get("HH_BOT_BASE", "/opt/hh-bot"))


def state_dir() -> Path:
    path = bot_base() / "state"
    path.mkdir(parents=True, exist_ok=True)
    return path


def dry_run_enabled() -> bool:
    return os.environ.get("HH_APPLY_DRY_RUN") == "1"


def send_enabled() -> bool:
    return os.environ.get("HH_APPLY_SEND_ENABLED") == "1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason: str
    log_code: str


@dataclass(frozen=True)
class Claim:
    key: str
    path: Path
    acquired: bool
    status: str = ""


def apply_key(vacancy_id: str | int, resume_id: str | int) -> str:
    return f"{resume_id}:{vacancy_id}"


def _claim_path(vacancy_id: str | int, resume_id: str | int) -> Path:
    raw_key = apply_key(vacancy_id, resume_id)
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    path = state_dir() / "apply_claims" / f"{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def claim_status(vacancy_id: str | int, resume_id: str | int) -> str | None:
    path = _claim_path(vacancy_id, resume_id)
    if not path.exists():
        return None
    return str(_read_json(path).get("status") or "claimed")


def terminal_status(status: str | None) -> bool:
    return status in {
        "sent",
        "already_applied",
        "locally_rejected",
        "ai_rejected",
        "needs_review",
        "malformed",
        "terminal_error",
        "archived",
        "discarded",
    }


def try_claim(
    vacancy_id: str | int,
    resume_id: str | int,
    *,
    owner: str,
    stage: str = "apply",
) -> Claim:
    path = _claim_path(vacancy_id, resume_id)
    key = apply_key(vacancy_id, resume_id)
    payload = {
        "key": key,
        "vacancy_id": str(vacancy_id),
        "resume_id": str(resume_id),
        "owner": owner,
        "stage": stage,
        "status": "claimed",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return Claim(
            key=key,
            path=path,
            acquired=False,
            status=str(_read_json(path).get("status") or "claimed"),
        )
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return Claim(key=key, path=path, acquired=True, status="claimed")


def update_claim(
    vacancy_id: str | int,
    resume_id: str | int,
    status: str,
    *,
    reason: str = "",
) -> None:
    path = _claim_path(vacancy_id, resume_id)
    payload = _read_json(path)
    payload.update(
        {
            "key": apply_key(vacancy_id, resume_id),
            "vacancy_id": str(vacancy_id),
            "resume_id": str(resume_id),
            "status": status,
            "reason": reason,
            "updated_at": now_iso(),
        }
    )
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def release_retryable_claim(
    vacancy_id: str | int,
    resume_id: str | int,
    *,
    reason: str,
) -> None:
    update_claim(vacancy_id, resume_id, "retryable_error", reason=reason)
    path = _claim_path(vacancy_id, resume_id)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


@contextmanager
def atomic_apply_claim(
    vacancy_id: str | int,
    resume_id: str | int,
    *,
    owner: str,
    stage: str = "apply",
) -> Iterator[Claim]:
    claim = try_claim(vacancy_id, resume_id, owner=owner, stage=stage)
    yield claim


def validate_cover_letter(message: str | None) -> GuardResult:
    text = (message or "").strip()
    if not text:
        return GuardResult(False, "empty_message", "blocked_empty_message")
    if CONTROL_MARKER_RE.search(text):
        return GuardResult(False, "control_marker", "blocked_control_marker")
    if len(text) < MIN_MEANINGFUL_LETTER_LEN:
        return GuardResult(False, "too_short_message", "blocked_invalid_message")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return GuardResult(False, "invalid_encoding", "blocked_invalid_message")
    return GuardResult(True, "ok", "allowed")


def guard_apply_post(
    vacancy_id: str | int,
    resume_id: str | int,
    message: str | None,
    *,
    stage: str,
) -> GuardResult:
    letter_guard = validate_cover_letter(message)
    if not letter_guard.allowed:
        logger.warning(
            "%s stage=%s vacancy_id=%s resume_id=%s reason=%s",
            letter_guard.log_code,
            stage,
            vacancy_id,
            resume_id,
            letter_guard.reason,
        )
        return letter_guard
    if dry_run_enabled():
        logger.info(
            "WOULD_APPLY stage=%s vacancy_id=%s resume_id=%s",
            stage,
            vacancy_id,
            resume_id,
        )
        return GuardResult(False, "dry_run", "WOULD_APPLY")
    if not send_enabled():
        logger.warning(
            "blocked_send_disabled stage=%s vacancy_id=%s resume_id=%s",
            stage,
            vacancy_id,
            resume_id,
        )
        return GuardResult(False, "send_disabled", "blocked_send_disabled")
    return GuardResult(True, "ok", "allowed")


def guard_apply_write(
    vacancy_id: str | int,
    resume_id: str | int,
    *,
    stage: str,
) -> GuardResult:
    if dry_run_enabled():
        logger.info(
            "WOULD_SKIP stage=%s vacancy_id=%s resume_id=%s",
            stage,
            vacancy_id,
            resume_id,
        )
        return GuardResult(False, "dry_run", "WOULD_SKIP")
    if not send_enabled():
        logger.warning(
            "blocked_send_disabled stage=%s vacancy_id=%s resume_id=%s",
            stage,
            vacancy_id,
            resume_id,
        )
        return GuardResult(False, "send_disabled", "blocked_send_disabled")
    return GuardResult(True, "ok", "allowed")
