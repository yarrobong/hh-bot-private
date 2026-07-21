from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_backfill_possible_ai_answer_creates_review_and_ask_request(tmp_path):
    fake_tool = tmp_path / "fake-hh-tool.py"
    fake_tool.write_text(
        """#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]
if args[:2] == ["call-api", "/negotiations"]:
    print(json.dumps({
        "items": [{
            "id": "neg-1",
            "state": {"id": "response"},
            "vacancy": {"name": "Python developer"},
            "employer": {"name": "ACME"},
        }]
    }, ensure_ascii=False))
elif args[:2] == ["call-api", "/negotiations/neg-1/messages"]:
    print(json.dumps({
        "items": [{
            "id": "msg-1",
            "created_at": "2026-07-21T12:00:00+0500",
            "text": "Есть ли у вас опыт Python?",
            "author": {"participant_type": "employer"},
        }]
    }, ensure_ascii=False))
else:
    print("{}")
""",
        encoding="utf-8",
    )
    fake_tool.chmod(0o755)

    env = {
        **os.environ,
        "HH_BOT_BASE": str(tmp_path),
        "HH_APPLICANT_TOOL_BIN": str(fake_tool),
        "HH_DISABLE_NTFY": "1",
    }
    result = subprocess.run(
        [sys.executable, "backfill_watch.py"],
        cwd=Path(__file__).resolve().parent.parent,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "possible_ai_answer" in result.stdout

    review = json.loads(
        (tmp_path / "state" / "backfill_review.json").read_text(
            encoding="utf-8"
        )
    )
    assert review[0]["reason"] == "possible_ai_answer"

    ask = json.loads(
        (tmp_path / "state" / "ask_requests" / "neg-1.json").read_text(
            encoding="utf-8"
        )
    )
    assert ask["status"] == "waiting"
    assert ask["reason"] == "possible_ai_answer"
