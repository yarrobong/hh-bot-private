from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any


logger = logging.getLogger(__package__)

CONTROL_MARKERS = ("__ASK__", "__SKIP__")
TERMINAL_STATUSES = {
    "sent",
    "skipped",
    "ignored",
    "asked",
    "human_flow_pending",
    "blocked_control_marker",
    "blocked_empty_message",
    "disabled_by_employer",
    "bootstrapped",
}


def bot_base() -> Path:
    return Path(os.environ.get("HH_BOT_BASE", "/opt/hh-bot"))


def state_dir() -> Path:
    return bot_base() / "state"


def seen_file() -> Path:
    return state_dir() / "reply_employers_seen.json"


def claims_dir() -> Path:
    return state_dir() / "reply_claims"


def is_dry_run() -> bool:
    return os.environ.get("HH_REPLY_DRY_RUN") == "1"


def send_enabled() -> bool:
    return os.environ.get("HH_REPLY_SEND_ENABLED") == "1"


def contains_control_marker(message: str) -> bool:
    upper = str(message or "").upper()
    return any(marker in upper for marker in CONTROL_MARKERS)


def clean_ai_marker(text: str, marker: str) -> str:
    marker_pos = text.upper().find(marker)
    if marker_pos < 0:
        return ""
    text = text[marker_pos + len(marker):].strip()
    if text.startswith(":"):
        text = text[1:].strip()
    return text


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def seen_key(nid: str, message_id: str) -> str:
    return f"{nid}:{message_id}"


def claim_name(nid: str, message_id: str) -> str:
    raw = seen_key(nid, message_id).encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest() + ".json"


def claim_path(nid: str, message_id: str) -> Path:
    return claims_dir() / claim_name(nid, message_id)


def load_seen() -> dict:
    return load_json(seen_file(), {})


def mark_seen(nid: str, message_id: str, status: str, **extra: str) -> None:
    seen = load_seen()
    seen[seen_key(nid, message_id)] = {
        "status": status,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        **extra,
    }
    save_json(seen_file(), seen)


def is_terminal(nid: str, message_id: str) -> bool:
    status = (load_seen().get(seen_key(nid, message_id), {}) or {}).get(
        "status"
    )
    if status in TERMINAL_STATUSES:
        return True
    claim = load_json(claim_path(nid, message_id), {})
    return claim.get("status") in TERMINAL_STATUSES


def try_claim(nid: str, message_id: str, owner: str) -> bool:
    if is_terminal(nid, message_id):
        return False

    path = claim_path(nid, message_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "negotiation_id": nid,
        "inbound_message_id": message_id,
        "owner": owner,
        "status": "claimed",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, 0o644)
    except FileExistsError:
        return False

    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return True


def mark_claim(nid: str, message_id: str, status: str, **extra: str) -> None:
    path = claim_path(nid, message_id)
    claim = load_json(path, {})
    claim.update(
        {
            "negotiation_id": nid,
            "inbound_message_id": message_id,
            "status": status,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            **extra,
        }
    )
    save_json(path, claim)
    if status in TERMINAL_STATUSES:
        mark_seen(nid, message_id, status, **extra)


def release_claim(nid: str, message_id: str, status: str, **extra: str) -> None:
    mark_claim(nid, message_id, status, **extra)
    path = claim_path(nid, message_id)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def would(action: str, nid: str, message_id: str, message: str = "") -> None:
    logger.info(
        "%s chat=%s inbound_message_id=%s message=%s",
        action,
        nid,
        message_id,
        message,
    )
    print(f"{action}: {nid} {message_id} {message}".rstrip())
