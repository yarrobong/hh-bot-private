#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from hh_applicant_tool import reply_safety


BASE = Path(os.environ.get("HH_BOT_BASE", "/opt/hh-bot"))
TOOL = os.environ.get(
    "HH_APPLICANT_TOOL_BIN",
    str(BASE / "venv" / "bin" / "hh-applicant-tool"),
)


def call_api(args):
    res = subprocess.run(
        [TOOL, "call-api", *args],
        text=True,
        capture_output=True,
    )
    if res.returncode != 0:
        print("API_ERROR:", " ".join(args), (res.stderr or res.stdout)[:500])
        return None
    raw = res.stdout.strip()
    if not raw.startswith("{"):
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def message_id(message):
    return str(
        message.get("id")
        or (
            str(message.get("created_at") or "")
            + ":"
            + str(abs(hash(message.get("text") or "")))
        )
    )


def iter_active_negotiations(max_pages):
    for page in range(max_pages):
        data = call_api(
            ["/negotiations", "status=active", f"page={page}", "per_page=100"]
        )
        if not data:
            continue
        items = data.get("items") or []
        if not items:
            break
        yield from items
        if page + 1 >= data.get("pages", 0):
            break


def last_employer_message(nid):
    data = call_api([f"/negotiations/{nid}/messages", "page=0", "per_page=100"])
    if not data:
        return None
    messages = sorted(
        data.get("items") or [],
        key=lambda item: item.get("created_at") or "",
    )
    employer_messages = [
        item
        for item in messages
        if (item.get("author") or {}).get("participant_type") == "employer"
    ]
    if not employer_messages:
        return None
    return employer_messages[-1]


def main():
    parser = argparse.ArgumentParser(
        description="Bootstrap reply_employers_seen.json from current HH chats."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-pages", type=int, default=25)
    args = parser.parse_args()

    processed = 0
    skipped = 0
    for negotiation in iter_active_negotiations(args.max_pages):
        nid = str(negotiation.get("id") or "")
        if not nid:
            skipped += 1
            continue
        last = last_employer_message(nid)
        if not last:
            skipped += 1
            continue
        mid = message_id(last)
        if args.dry_run:
            print(f"WOULD_BOOTSTRAP: {nid} {mid}")
        else:
            reply_safety.mark_seen(nid, mid, "bootstrapped")
        processed += 1

    print(f"BOOTSTRAP_REPLY_SEEN processed={processed} skipped={skipped}")


if __name__ == "__main__":
    main()
