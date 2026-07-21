from __future__ import annotations

import json
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pytest
from requests import Response

from hh_applicant_tool import reply_safety
from hh_applicant_tool.api.errors import Forbidden
from hh_applicant_tool.operations.reply_employers import Operation


UPDATED_AT = "2026-07-21T12:00:00+0500"


@dataclass
class FakeAI:
    answer: str

    def complete(self, query: str) -> str:
        return self.answer


class FakeApiClient:
    def __init__(self, messages, post_error=None):
        self.messages = messages
        self.post_error = post_error
        self.posts = []

    def get(self, endpoint, **kwargs):
        assert endpoint.endswith("/messages")
        return {"items": self.messages, "pages": 1}

    def post(self, endpoint, **kwargs):
        self.posts.append((endpoint, kwargs))
        if self.post_error:
            raise self.post_error
        return {}


class FakeTool:
    def __init__(self, api_client, negotiations, ai_answer=""):
        self.api_client = api_client
        self.negotiations = negotiations
        self.ai_answer = ai_answer
        self.config = {}

    def first_resume_id(self):
        return None

    def get_blacklisted(self):
        return []

    def get_me(self):
        return {"first_name": "Ярослав", "last_name": "", "email": ""}

    def get_resumes(self):
        return [
            {
                "id": "resume-1",
                "title": "Python developer",
                "status": {"id": "published"},
            }
        ]

    def get_negotiations(self, max_pages=None):
        return self.negotiations

    def get_cover_letter_ai(self, system_prompt):
        return FakeAI(self.ai_answer)


def message(
    participant_type,
    text,
    message_id,
    created_at="2026-07-21T12:00:00+0500",
):
    return {
        "id": message_id,
        "text": text,
        "created_at": created_at,
        "author": {"participant_type": participant_type},
    }


def employer_message(text="Готовы пройти тест?", message_id="msg-1"):
    return message("employer", text, message_id)


def applicant_message(text="Здравствуйте!", message_id="app-1"):
    return message("applicant", text, message_id)


def negotiation(state="response"):
    return {
        "id": "neg-1",
        "resume": {"id": "resume-1"},
        "updated_at": UPDATED_AT,
        "state": {"id": state},
        "viewed_by_opponent": True,
        "vacancy": {
            "name": "Python developer",
            "alternate_url": "https://hh.ru/vacancy/1",
            "employer": {"id": "emp-1", "name": "ACME"},
            "salary": None,
        },
    }


def args(**overrides):
    values = {
        "reply_message": None,
        "max_pages": 10,
        "dry_run": False,
        "only_invitations": False,
        "use_ai": True,
        "system_prompt": "system",
        "message_prompt": "prompt",
        "period": None,
    }
    values.update(overrides)
    return Namespace(**values)


@pytest.mark.parametrize("state", ["response", "interview"])
def test_ai_ask_is_saved_for_human_and_not_sent(tmp_path, monkeypatch, state):
    monkeypatch.setenv("HH_BOT_BASE", str(tmp_path))
    api = FakeApiClient([employer_message()])
    tool = FakeTool(api, [negotiation(state)], "__ASK__: Готов пройти тест?")

    Operation().run(tool, args())

    assert api.posts == []
    ask_path = tmp_path / "state" / "ask_requests" / "neg-1.json"
    ask = json.loads(ask_path.read_text(encoding="utf-8"))
    assert ask["status"] == "waiting"
    assert ask["ask_text"] == "Готов пройти тест?"
    assert ask["vacancy"] == "Python developer"
    assert ask["inbound_message_id"] == "msg-1"


def test_ai_skip_is_not_sent(tmp_path, monkeypatch):
    monkeypatch.setenv("HH_BOT_BASE", str(tmp_path))
    api = FakeApiClient([employer_message("Спасибо, мы свяжемся")])
    tool = FakeTool(api, [negotiation()], "__SKIP__")

    Operation().run(tool, args())

    assert api.posts == []
    assert not (tmp_path / "state" / "ask_requests" / "neg-1.json").exists()
    seen = json.loads(
        (tmp_path / "state" / "reply_employers_seen.json").read_text(
            encoding="utf-8"
        )
    )
    assert seen["neg-1:msg-1"]["status"] == "skipped"


def test_only_applicant_messages_are_never_sent(tmp_path, monkeypatch):
    monkeypatch.setenv("HH_BOT_BASE", str(tmp_path))
    api = FakeApiClient([applicant_message()])
    tool = FakeTool(api, [negotiation()], "Здравствуйте! Готов обсудить.")

    Operation().run(tool, args())

    assert api.posts == []


def test_last_applicant_message_is_never_sent(tmp_path, monkeypatch):
    monkeypatch.setenv("HH_BOT_BASE", str(tmp_path))
    api = FakeApiClient(
        [
            employer_message("Есть ли опыт Python?", "msg-1"),
            applicant_message(
                "Здравствуйте! Да, опыт есть.",
                "app-1",
            ),
        ]
    )
    tool = FakeTool(api, [negotiation()], "Здравствуйте! Готов уточнить детали.")

    Operation().run(tool, args())

    assert api.posts == []


def test_employer_question_gets_exactly_one_post(tmp_path, monkeypatch):
    monkeypatch.setenv("HH_BOT_BASE", str(tmp_path))
    monkeypatch.setenv("HH_REPLY_SEND_ENABLED", "1")
    api = FakeApiClient([employer_message("Есть ли опыт Python?", "msg-1")])
    tool = FakeTool(api, [negotiation()], "Здравствуйте! Да, опыт есть.")

    Operation().run(tool, args())

    assert len(api.posts) == 1
    assert api.posts[0][1]["message"] == "Здравствуйте! Да, опыт есть."


def test_repeated_run_without_new_employer_message_does_not_post(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("HH_BOT_BASE", str(tmp_path))
    monkeypatch.setenv("HH_REPLY_SEND_ENABLED", "1")
    api = FakeApiClient([employer_message("Есть ли опыт Python?", "msg-1")])
    tool = FakeTool(api, [negotiation()], "Здравствуйте! Да, опыт есть.")

    Operation().run(tool, args())
    Operation().run(tool, args())

    assert len(api.posts) == 1


def test_existing_human_flow_for_same_message_blocks_ai_send(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("HH_BOT_BASE", str(tmp_path))
    ask_path = tmp_path / "state" / "ask_requests" / "neg-1.json"
    ask_path.parent.mkdir(parents=True)
    ask_path.write_text(
        json.dumps(
            {
                "nid": "neg-1",
                "status": "waiting",
                "inbound_message_id": "msg-1",
                "ask_text": "Есть ли опыт Python?",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    api = FakeApiClient([employer_message("Есть ли опыт Python?", "msg-1")])
    tool = FakeTool(api, [negotiation()], "Здравствуйте! Да, опыт есть.")

    Operation().run(tool, args())

    assert api.posts == []


def test_two_handlers_can_claim_same_message_only_once(tmp_path, monkeypatch):
    monkeypatch.setenv("HH_BOT_BASE", str(tmp_path))

    def claim(owner):
        return reply_safety.try_claim("neg-1", "msg-1", owner)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ["handler-a", "handler-b"]))

    assert sorted(results) == [False, True]


def test_drafted_human_answer_is_sent_and_marked_sent(tmp_path, monkeypatch):
    monkeypatch.setenv("HH_BOT_BASE", str(tmp_path))
    monkeypatch.setenv("HH_REPLY_SEND_ENABLED", "1")
    answer_path = tmp_path / "state" / "human_answers" / "neg-1.json"
    answer_path.parent.mkdir(parents=True)
    answer_path.write_text(
        json.dumps(
            {
                "nid": "neg-1",
                "status": "drafted",
                "inbound_message_id": "msg-1",
                "draft_message": "Здравствуйте! Да, готов обсудить детали.",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    api = FakeApiClient([employer_message()])
    tool = FakeTool(api, [negotiation()])

    Operation().run(tool, args(use_ai=False))

    assert len(api.posts) == 1
    endpoint, payload = api.posts[0]
    assert endpoint == "/negotiations/neg-1/messages"
    assert payload["message"] == "Здравствуйте! Да, готов обсудить детали."
    assert 1 <= payload["delay"] <= 3
    saved = json.loads(answer_path.read_text(encoding="utf-8"))
    assert saved["status"] == "sent"


def test_drafted_human_answer_without_inbound_message_id_is_not_sent(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("HH_BOT_BASE", str(tmp_path))
    answer_path = tmp_path / "state" / "human_answers" / "neg-1.json"
    answer_path.parent.mkdir(parents=True)
    answer_path.write_text(
        json.dumps(
            {
                "nid": "neg-1",
                "status": "drafted",
                "draft_message": "Здравствуйте! Да, готов обсудить детали.",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    api = FakeApiClient([employer_message()])
    tool = FakeTool(api, [negotiation()])

    Operation().run(tool, args(use_ai=False))

    assert api.posts == []


def test_disabled_by_employer_marks_answer_terminal(tmp_path, monkeypatch):
    monkeypatch.setenv("HH_BOT_BASE", str(tmp_path))
    monkeypatch.setenv("HH_REPLY_SEND_ENABLED", "1")
    answer_path = tmp_path / "state" / "human_answers" / "neg-1.json"
    answer_path.parent.mkdir(parents=True)
    answer_path.write_text(
        json.dumps(
            {
                "nid": "neg-1",
                "status": "drafted",
                "inbound_message_id": "msg-1",
                "draft_message": "Здравствуйте! Да, готов обсудить детали.",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = Response()
    response.status_code = 403
    error = Forbidden(
        response,
        {"errors": [{"type": "negotiations", "value": "disabled_by_employer"}]},
    )
    api = FakeApiClient([employer_message()], post_error=error)
    tool = FakeTool(api, [negotiation()])

    Operation().run(tool, args(use_ai=False))

    saved = json.loads(answer_path.read_text(encoding="utf-8"))
    assert saved["status"] == "disabled_by_employer"


def test_send_disabled_by_default_blocks_post(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("HH_BOT_BASE", str(tmp_path))
    monkeypatch.delenv("HH_REPLY_SEND_ENABLED", raising=False)
    api = FakeApiClient([employer_message("Есть ли опыт Python?", "msg-1")])
    tool = FakeTool(api, [negotiation()], "Здравствуйте! Да, опыт есть.")

    Operation().run(tool, args())

    assert api.posts == []
    assert "blocked_send_disabled" in caplog.text


def test_dry_run_blocks_post_even_when_send_enabled(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HH_BOT_BASE", str(tmp_path))
    monkeypatch.setenv("HH_REPLY_SEND_ENABLED", "1")
    monkeypatch.setenv("HH_REPLY_DRY_RUN", "1")
    api = FakeApiClient([employer_message("Есть ли опыт Python?", "msg-1")])
    tool = FakeTool(api, [negotiation()], "Здравствуйте! Да, опыт есть.")

    Operation().run(tool, args())

    assert api.posts == []
    assert "WOULD_SEND" in capsys.readouterr().out
    assert not (tmp_path / "state" / "reply_employers_seen.json").exists()


@pytest.mark.parametrize("raw", ["__ASK__: Готовы?", "__SKIP__", ""])
def test_send_message_blocks_control_markers_and_empty_text(
    tmp_path,
    monkeypatch,
    caplog,
    raw,
):
    monkeypatch.setenv("HH_BOT_BASE", str(tmp_path))
    api = FakeApiClient([employer_message()])
    op = Operation()
    op.api_client = api
    op.dry_run = False

    sent = op._send_message(
        nid="neg-1",
        vacancy={
            "alternate_url": "https://hh.ru/vacancy/1",
        },
        send_message=raw,
        inbound_message_id="msg-1",
    )

    assert sent is False
    assert api.posts == []
    log_text = caplog.text
    assert "blocked_" in log_text
