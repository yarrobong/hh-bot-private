#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime
from pathlib import Path


BASE = Path(os.environ.get("HH_BOT_BASE", "/opt/hh-bot"))
STATE = BASE / "state"
ASK_DIR = STATE / "ask_requests"
ANS_DIR = STATE / "human_answers"
ARCHIVE_ROOT = STATE / "reply_pending_archive"

PENDING_STATUSES = {
    "answered",
    "drafted",
    "needs_review",
    "new",
    "waiting",
}


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def archive_path(src, archive_dir):
    dst = archive_dir / src.parent.name / src.name
    if not dst.exists():
        return dst
    stem = dst.stem
    suffix = dst.suffix
    for index in range(1, 10_000):
        candidate = dst.with_name(f"{stem}.{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Cannot find archive name for {src}")


def should_archive(path):
    data = load_json(path)
    if data.get("inbound_message_id") or data.get("last_employer_message_id"):
        return False
    status = data.get("status") or "waiting"
    return status in PENDING_STATUSES


def iter_pending_files():
    for folder in (ASK_DIR, ANS_DIR):
        if not folder.exists():
            continue
        yield from sorted(folder.glob("*.json"))


def main():
    parser = argparse.ArgumentParser(
        description="Archive old reply pending files without inbound_message_id."
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    archive_dir = ARCHIVE_ROOT / datetime.now().strftime("%Y%m%d-%H%M%S")
    selected = [path for path in iter_pending_files() if should_archive(path)]

    for src in selected:
        dst = archive_path(src, archive_dir)
        print(f"{'WOULD_ARCHIVE' if args.dry_run else 'ARCHIVE'}: {src} -> {dst}")
        if args.dry_run:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))

    print(f"CLEANUP_REPLY_PENDING archived={0 if args.dry_run else len(selected)} candidates={len(selected)}")


if __name__ == "__main__":
    main()
