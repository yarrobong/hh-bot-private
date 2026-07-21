from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.test_reply_employers import (
    FakeApiClient,
    FakeTool,
    args,
    employer_message,
    negotiation,
)
from hh_applicant_tool.operations.reply_employers import Operation


def write_fake_tool(tmp_path):
    calls_file = tmp_path / "calls.jsonl"
    fake_tool = tmp_path / "fake-hh-tool.py"
    fake_tool.write_text(
        f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

calls = Path({str(calls_file)!r})
with calls.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\\n")

args = sys.argv[1:]
if "-m" in args or "POST" in args:
    raise SystemExit(2)
if args[:2] == ["call-api", "/negotiations"]:
    print(json.dumps({{
        "items": [{{
            "id": "neg-1",
            "state": {{"id": "response"}},
            "vacancy": {{"name": "Python developer"}},
            "employer": {{"name": "ACME"}},
        }}],
        "pages": 1,
    }}, ensure_ascii=False))
elif args[:2] == ["call-api", "/negotiations/neg-1/messages"]:
    print(json.dumps({{
        "items": [{{
            "id": "msg-1",
            "created_at": "2026-07-21T12:00:00+0500",
            "text": "Есть ли у вас опыт Python?",
            "author": {{"participant_type": "employer"}},
        }}],
        "pages": 1,
    }}, ensure_ascii=False))
else:
    print("{{}}")
""",
        encoding="utf-8",
    )
    fake_tool.chmod(0o755)
    return fake_tool, calls_file


def run_bootstrap(tmp_path, *extra_args):
    fake_tool, calls_file = write_fake_tool(tmp_path)
    env = {
        **os.environ,
        "HH_BOT_BASE": str(tmp_path),
        "HH_APPLICANT_TOOL_BIN": str(fake_tool),
    }
    result = subprocess.run(
        [sys.executable, "bootstrap_reply_seen.py", *extra_args],
        cwd=Path(__file__).resolve().parent.parent,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return result, calls_file


def test_bootstrap_does_not_post(tmp_path):
    result, calls_file = run_bootstrap(tmp_path, "--dry-run")

    assert "BOOTSTRAP_REPLY_SEEN processed=1 skipped=0" in result.stdout
    calls = calls_file.read_text(encoding="utf-8")
    assert "POST" not in calls
    assert not (tmp_path / "state" / "reply_employers_seen.json").exists()


def test_bootstrap_prevents_processing_old_employer_message(
    tmp_path,
    monkeypatch,
):
    run_bootstrap(tmp_path)
    monkeypatch.setenv("HH_BOT_BASE", str(tmp_path))
    monkeypatch.setenv("HH_REPLY_SEND_ENABLED", "1")
    api = FakeApiClient([employer_message("Есть ли опыт Python?", "msg-1")])
    tool = FakeTool(api, [negotiation()], "Здравствуйте! Да, опыт есть.")

    Operation().run(tool, args())

    assert api.posts == []


def test_new_employer_message_after_bootstrap_is_processed(
    tmp_path,
    monkeypatch,
):
    run_bootstrap(tmp_path)
    monkeypatch.setenv("HH_BOT_BASE", str(tmp_path))
    monkeypatch.setenv("HH_REPLY_SEND_ENABLED", "1")
    api = FakeApiClient([employer_message("Есть ли опыт Python?", "msg-2")])
    tool = FakeTool(api, [negotiation()], "Здравствуйте! Да, опыт есть.")

    Operation().run(tool, args())

    assert len(api.posts) == 1
