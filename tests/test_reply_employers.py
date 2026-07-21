from __future__ import annotations

import json
from argparse import Namespace
from dataclasses import dataclass

import pytest
from requests import Response

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


def employer_message(text="Готовы пройти тест?"):
    return {
        "id": "msg-1",
        "text": text,
        "created_at": UPDATED_AT,
        "author": {"participant_type": "employer"},
    }


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


def test_ai_skip_is_not_sent(tmp_path, monkeypatch):
    monkeypatch.setenv("HH_BOT_BASE", str(tmp_path))
    api = FakeApiClient([employer_message("Спасибо, мы свяжемся")])
    tool = FakeTool(api, [negotiation()], "__SKIP__")

    Operation().run(tool, args())

    assert api.posts == []
    assert not (tmp_path / "state" / "ask_requests" / "neg-1.json").exists()


def test_drafted_human_answer_is_sent_and_marked_sent(tmp_path, monkeypatch):
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

    assert len(api.posts) == 1
    endpoint, payload = api.posts[0]
    assert endpoint == "/negotiations/neg-1/messages"
    assert payload["message"] == "Здравствуйте! Да, готов обсудить детали."
    assert 1 <= payload["delay"] <= 3
    saved = json.loads(answer_path.read_text(encoding="utf-8"))
    assert saved["status"] == "sent"


def test_disabled_by_employer_marks_answer_terminal(tmp_path, monkeypatch):
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
