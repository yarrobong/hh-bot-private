from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_send_human_answers_dry_run_does_not_mutate_pending_answer(tmp_path):
    ask_dir = tmp_path / "state" / "ask_requests"
    ans_dir = tmp_path / "state" / "human_answers"
    ask_dir.mkdir(parents=True)
    ans_dir.mkdir(parents=True)
    (ask_dir / "neg-1.json").write_text(
        json.dumps(
            {
                "nid": "neg-1",
                "status": "answered",
                "ask_text": "Есть ли опыт Python?",
                "inbound_message_id": "msg-1",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    answer_path = ans_dir / "neg-1.json"
    answer_path.write_text(
        json.dumps(
            {
                "nid": "neg-1",
                "status": "new",
                "answer": "Да, есть опыт Python и Django в коммерческих задачах.",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "send_human_answers.py"],
        cwd=Path(__file__).resolve().parent.parent,
        env={
            **os.environ,
            "HH_BOT_BASE": str(tmp_path),
            "HH_REPLY_DRY_RUN": "1",
        },
        text=True,
        capture_output=True,
        check=True,
    )

    assert "WOULD_SEND" in result.stdout
    saved = json.loads(answer_path.read_text(encoding="utf-8"))
    assert saved["status"] == "new"
    assert "draft_message" not in saved
