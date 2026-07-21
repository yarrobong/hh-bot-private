from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from hh_applicant_tool import apply_safety
from hh_applicant_tool.apply_pipeline import (
    AuthorizationError,
    FakeAIEvaluator,
    FakeApplyTransport,
    fixture_matrix,
    fixture_vacancy,
    real_dry_run_regression_vacancies,
    normalize_vacancy,
    parse_ai_decision,
    run_apply_pipeline,
    VacancyEvaluator,
)
from hh_applicant_tool.operations.apply_vacancies import Operation, VacancyParsingError


@pytest.fixture(autouse=True)
def isolated_apply_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HH_BOT_BASE", str(tmp_path))
    monkeypatch.delenv("HH_APPLY_SEND_ENABLED", raising=False)
    monkeypatch.delenv("HH_APPLY_DRY_RUN", raising=False)


def test_default_real_post_is_blocked():
    transport = FakeApplyTransport()
    result = run_apply_pipeline(
        [fixture_vacancy("1", "Python backend", "apply")],
        transport=transport,
    )

    assert transport.posts == []
    assert result.metrics.actual_sent == 0
    assert result.metrics.terminal_error == 1
    assert result.decisions[0].reason == "send_disabled"


def test_send_enabled_allows_one_valid_post(monkeypatch):
    monkeypatch.setenv("HH_APPLY_SEND_ENABLED", "1")
    transport = FakeApplyTransport()

    result = run_apply_pipeline(
        [fixture_vacancy("1", "Python backend", "apply")],
        transport=transport,
    )

    assert len(transport.posts) == 1
    assert result.metrics.successfully_sent == 1
    assert result.metrics.actual_sent == 1


def test_dry_run_blocks_post_even_when_send_enabled(monkeypatch):
    monkeypatch.setenv("HH_APPLY_SEND_ENABLED", "1")
    monkeypatch.setenv("HH_APPLY_DRY_RUN", "1")
    transport = FakeApplyTransport()

    result = run_apply_pipeline(
        [fixture_vacancy("1", "Python backend", "apply")],
        transport=transport,
    )

    assert transport.posts == []
    assert result.metrics.actual_sent == 0
    assert result.metrics.would_apply == 1


def test_one_suitable_vacancy_produces_one_would_apply(monkeypatch):
    monkeypatch.setenv("HH_APPLY_DRY_RUN", "1")

    result = run_apply_pipeline([fixture_vacancy("1", "Python backend", "apply")])

    assert result.metrics.would_apply == 1
    assert result.decisions[0].would_apply is True


def test_repeat_run_after_success_creates_zero_new_actions(monkeypatch):
    monkeypatch.setenv("HH_APPLY_SEND_ENABLED", "1")
    vacancy = fixture_vacancy("1", "Python backend", "apply")
    first = FakeApplyTransport()
    second = FakeApplyTransport()

    assert run_apply_pipeline([vacancy], transport=first).metrics.actual_sent == 1
    result = run_apply_pipeline([vacancy], transport=second)

    assert second.posts == []
    assert result.metrics.duplicate == 1
    assert result.metrics.actual_sent == 0


def test_same_vacancy_from_two_queries_gets_one_claim(monkeypatch):
    monkeypatch.setenv("HH_APPLY_SEND_ENABLED", "1")
    transport = FakeApplyTransport()

    result = run_apply_pipeline(
        [
            fixture_vacancy("1", "Python backend query A", "apply"),
            fixture_vacancy("1", "Python backend query B", "already_processed"),
        ],
        transport=transport,
    )

    assert len(transport.posts) == 1
    assert result.metrics.duplicate == 1


def test_unsuitable_vacancy_gets_zero_post(monkeypatch):
    monkeypatch.setenv("HH_APPLY_SEND_ENABLED", "1")
    transport = FakeApplyTransport()

    result = run_apply_pipeline(
        [fixture_vacancy("1", "Оператор call center", "skip", text="call center")],
        transport=transport,
    )

    assert transport.posts == []
    assert result.metrics.locally_rejected == 1


def test_needs_review_gets_zero_post(monkeypatch):
    monkeypatch.setenv("HH_APPLY_SEND_ENABLED", "1")
    transport = FakeApplyTransport()

    result = run_apply_pipeline(
        [fixture_vacancy("1", "Python с анкетой", "needs_review", response_url="https://hh.ru/form")],
        transport=transport,
    )

    assert transport.posts == []
    assert result.metrics.needs_review == 1


def test_ai_exception_is_fail_safe_zero_post(monkeypatch):
    monkeypatch.setenv("HH_APPLY_SEND_ENABLED", "1")
    transport = FakeApplyTransport()

    result = run_apply_pipeline(
        [fixture_vacancy("1", "Python backend", "apply")],
        ai=FakeAIEvaluator({"1": RuntimeError("boom")}),
        transport=transport,
    )

    assert transport.posts == []
    assert result.metrics.needs_review == 1
    assert result.decisions[0].reason == "ai_exception:RuntimeError"


def test_malformed_vacancy_cycle_continues(monkeypatch):
    monkeypatch.setenv("HH_APPLY_DRY_RUN", "1")

    result = run_apply_pipeline(
        [
            {"name": "Без id", "alternate_url": ""},
            fixture_vacancy("2", "Python backend", "apply"),
        ]
    )

    assert result.metrics.malformed == 1
    assert result.metrics.would_apply == 1


@pytest.mark.parametrize(
    "raw",
    [
        {"id": "1", "name": "Python", "salary": None},
        {"id": "1", "name": "Python", "employer": None},
        {
            "id": "1",
            "name": "Python",
            "snippet": {"requirement": None, "responsibility": None},
        },
        {"id": "1", "name": "Python", "schedule": None, "experience": None},
        {
            "name": "Python",
            "alternate_url": "https://hh.ru/vacancy/123",
            "area": None,
            "employer": None,
            "snippet": None,
        },
    ],
)
def test_problematic_fields_do_not_crash(raw):
    normalized, reason = normalize_vacancy(raw)

    assert reason == "ok"
    assert normalized is not None


def test_unexpected_url_is_malformed_not_nonetype_group():
    normalized, reason = normalize_vacancy(
        {"id": "1", "name": "Python", "alternate_url": "not-a-hh-vacancy"}
    )

    assert normalized is None
    assert reason == "unexpected_url"


@pytest.mark.parametrize(
    ("response", "expected", "reason"),
    [
        ('{"decision":"apply"}', "apply", "ai_ok"),
        ('{"decision":"skip"}', "skip", "ai_ok"),
        ('{"decision":"needs_review"}', "needs_review", "ai_ok"),
        ("", "needs_review", "ai_empty"),
        ("not json", "needs_review", "ai_invalid_json"),
        ('text {"decision":"apply"} tail', "apply", "ai_ok"),
        ('{"decision":"unknown"}', "needs_review", "ai_unknown_marker"),
        ('{"decision":"apply","suitable":false}', "needs_review", "ai_contradictory"),
    ],
)
def test_ai_response_variants(response, expected, reason):
    assert parse_ai_decision(response) == (expected, reason)


def test_hard_exclusions_have_priority_over_ai(monkeypatch):
    monkeypatch.setenv("HH_APPLY_SEND_ENABLED", "1")
    transport = FakeApplyTransport()

    result = run_apply_pipeline(
        [fixture_vacancy("1", "Python sales", "skip", text="продажи Python")],
        ai=FakeAIEvaluator({"1": '{"decision":"apply"}'}),
        transport=transport,
    )

    assert transport.posts == []
    assert result.metrics.locally_rejected == 1


@pytest.mark.parametrize(
    ("vacancy", "reason"),
    [
        (
            fixture_vacancy(
                "8001",
                "Python Django junior",
                "skip",
                area="Краснодар",
                schedule="fullDay",
                work_format="Гибрид",
            ),
            "office_or_hybrid_not_ekb",
        ),
        (
            fixture_vacancy(
                "8002",
                "Junior LLM Engineer",
                "skip",
                area="Казань",
                schedule="fullDay",
                work_format="Гибрид",
            ),
            "office_or_hybrid_not_ekb",
        ),
        (
            fixture_vacancy(
                "8003",
                "Младший Fullstack разработчик",
                "skip",
                area="Симферополь",
                schedule="fullDay",
                work_format="На месте работодателя",
            ),
            "office_not_ekb",
        ),
        (
            fixture_vacancy(
                "8004",
                "Data Scientist junior",
                "skip",
                area="Нижний Новгород",
                schedule="fullDay",
                work_format="Офис",
                text="Machine Learning RecSys Python",
            ),
            "office_not_ekb+role_mismatch",
        ),
        (
            fixture_vacancy(
                "8005",
                "Преподаватель по информатике",
                "skip",
                area="Казань",
                schedule="fullDay",
                work_format="На месте работодателя",
                text="учитель педагог работа с детьми",
            ),
            "office_not_ekb+teaching_children",
        ),
    ],
)
def test_geography_and_hard_exclusion_cases(vacancy, reason):
    normalized, parse_reason = normalize_vacancy(vacancy)
    assert parse_reason == "ok"
    assert normalized is not None

    assert VacancyEvaluator().evaluate(normalized) == ("skip", reason)


@pytest.mark.parametrize("vacancy", real_dry_run_regression_vacancies())
def test_real_server_dry_run_regression_fixtures_zero_would_apply(monkeypatch, vacancy):
    monkeypatch.setenv("HH_APPLY_DRY_RUN", "1")
    transport = FakeApplyTransport()

    result = run_apply_pipeline(
        [vacancy],
        ai=FakeAIEvaluator({vacancy["id"]: '{"decision":"apply"}'}),
        transport=transport,
    )

    assert result.metrics.would_apply == 0
    assert result.metrics.actual_sent == 0
    assert transport.posts == []
    assert result.decisions[0].decision == "skip"


def test_remote_moscow_is_allowed_when_remote_confirmed(monkeypatch):
    monkeypatch.setenv("HH_APPLY_DRY_RUN", "1")
    vacancy = fixture_vacancy(
        "8010",
        "Python backend",
        "apply",
        area="Москва",
        schedule="remote",
    )

    result = run_apply_pipeline([vacancy])

    assert result.metrics.would_apply == 1


@pytest.mark.parametrize("work_format", ["Офис", "Гибрид"])
def test_ekb_office_or_hybrid_is_allowed(monkeypatch, work_format):
    monkeypatch.setenv("HH_APPLY_DRY_RUN", "1")
    vacancy = fixture_vacancy(
        "8020",
        "Python backend",
        "apply",
        area="Екатеринбург",
        schedule="fullDay",
        work_format=work_format,
    )

    result = run_apply_pipeline([vacancy])

    assert result.metrics.would_apply == 1


def test_unknown_area_and_unknown_work_format_needs_review():
    vacancy = fixture_vacancy(
        "8030",
        "Python backend",
        "needs_review",
        area="",
        schedule="",
        work_format="",
    )
    normalized, _ = normalize_vacancy(vacancy)

    assert normalized is not None
    assert VacancyEvaluator().evaluate(normalized) == (
        "needs_review",
        "unknown_location_or_format",
    )


class FakeApplyApiClient:
    def __init__(self, full_vacancy):
        self.full_vacancy = full_vacancy
        self.posts = []

    def get(self, endpoint, params=None):
        if endpoint.startswith("/vacancies/"):
            return self.full_vacancy
        raise AssertionError(endpoint)

    def post(self, *args, **kwargs):
        self.posts.append((args, kwargs))
        raise AssertionError("POST must not be called")

    def put(self, *args, **kwargs):
        raise AssertionError("PUT must not be called")


def test_search_snippet_suitable_but_full_vacancy_city_skips_after_enrichment():
    search = fixture_vacancy(
        "8040",
        "Python Django junior",
        "apply",
        area="Россия",
        schedule="remote",
    )
    search.pop("work_format")
    search.pop("description", None)
    full = {
        **search,
        "area": {"name": "Краснодар"},
        "schedule": {"id": "fullDay"},
        "work_format": [{"name": "Гибрид"}],
        "description": "Периодически необходимо работать на территории работодателя.",
    }
    op = Operation()
    op.tool = type("Tool", (), {"api_client": FakeApplyApiClient(full)})()

    enriched, decision, reason = op._prepare_and_evaluate_vacancy(search)
    normalized, _ = normalize_vacancy(enriched)

    assert decision == "skip"
    assert reason == "office_or_hybrid_not_ekb"
    assert normalized is not None
    assert normalized.area == "Краснодар"


def test_production_prepare_and_fixture_pipeline_same_decision(monkeypatch):
    monkeypatch.setenv("HH_APPLY_DRY_RUN", "1")
    vacancy = real_dry_run_regression_vacancies()[0]
    op = Operation()
    op.tool = type("Tool", (), {"api_client": FakeApplyApiClient(vacancy)})()

    _, prod_decision, prod_reason = op._prepare_and_evaluate_vacancy(vacancy)
    fixture_result = run_apply_pipeline([vacancy])

    assert fixture_result.decisions[0].decision == prod_decision
    assert fixture_result.decisions[0].reason == prod_reason


@pytest.mark.parametrize("outcome", ["409"])
def test_already_applied_actual_sent_zero(monkeypatch, outcome):
    monkeypatch.setenv("HH_APPLY_SEND_ENABLED", "1")
    result = run_apply_pipeline(
        [fixture_vacancy("1", "Python backend", "apply")],
        transport=FakeApplyTransport({"1": outcome}),
    )

    assert result.metrics.already_applied == 1
    assert result.metrics.actual_sent == 0


def test_employer_rejection_actual_sent_zero(monkeypatch):
    monkeypatch.setenv("HH_APPLY_SEND_ENABLED", "1")
    result = run_apply_pipeline(
        [fixture_vacancy("1", "Python backend", "already_processed", relations=["got_rejection"])]
    )

    assert result.metrics.actual_sent == 0
    assert result.decisions[0].reason == "employer_rejection"


@pytest.mark.parametrize("outcome", ["429", "500", "502", "503", "timeout", "connection"])
def test_retryable_api_errors_are_bounded(monkeypatch, outcome):
    monkeypatch.setenv("HH_APPLY_SEND_ENABLED", "1")
    transport = FakeApplyTransport({"1": outcome})

    result = run_apply_pipeline(
        [fixture_vacancy("1", "Python backend", "apply")],
        transport=transport,
    )

    assert transport.attempts["1"] == 1
    assert result.metrics.retryable_error == 1
    assert result.metrics.actual_sent == 0


def test_401_stops_with_clear_authorization_error(monkeypatch):
    monkeypatch.setenv("HH_APPLY_SEND_ENABLED", "1")

    with pytest.raises(AuthorizationError, match="HTTP 401"):
        run_apply_pipeline(
            [
                fixture_vacancy("1", "Python backend", "apply"),
                fixture_vacancy("2", "Python backend 2", "apply"),
            ],
            transport=FakeApplyTransport({"1": "401"}),
        )


def test_parallel_workers_post_at_most_once(monkeypatch):
    monkeypatch.setenv("HH_APPLY_SEND_ENABLED", "1")
    vacancy = [fixture_vacancy("1", "Python backend", "apply")]

    def worker():
        transport = FakeApplyTransport()
        return run_apply_pipeline(vacancy, transport=transport), transport

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))

    posts = sum(len(transport.posts) for _, transport in results)
    sent = sum(result.metrics.actual_sent for result, _ in results)
    assert posts <= 1
    assert sent <= 1


@pytest.mark.parametrize("message", ["__ASK__: вопрос", "__SKIP__", ""])
def test_final_send_guard_blocks_control_markers_and_empty(message):
    guard = apply_safety.guard_apply_post("1", "resume-1", message, stage="test")

    assert guard.allowed is False
    assert guard.log_code in {
        "blocked_control_marker",
        "blocked_empty_message",
        "blocked_invalid_message",
    }


def test_old_human_answer_without_inbound_message_id_does_not_affect_apply(monkeypatch):
    monkeypatch.setenv("HH_APPLY_SEND_ENABLED", "1")
    result = run_apply_pipeline(
        [fixture_vacancy("1", "Python backend", "apply")],
        transport=FakeApplyTransport(),
    )

    assert result.metrics.actual_sent == 1


def test_fixture_matrix_expected_decisions_in_dry_run(monkeypatch):
    monkeypatch.setenv("HH_APPLY_DRY_RUN", "1")
    result = run_apply_pipeline(fixture_matrix())

    expected = [item["expected_decision"] for item in fixture_matrix()]
    actual = [decision.decision for decision in result.decisions]
    assert actual == expected
    assert result.metrics.found >= 40
    assert result.metrics.actual_sent == 0


class FakeResponse:
    text = "<html>no embedded description</html>"

    def raise_for_status(self):
        return None


class FakeSession:
    def get(self, *args, **kwargs):
        return FakeResponse()


def test_legacy_excluded_parser_reports_parse_error_without_group_crash():
    op = Operation()
    op.excluded_filter = "продажи"
    op.tool = type("Tool", (), {"session": FakeSession()})()

    with pytest.raises(VacancyParsingError, match="description_not_found"):
        op._is_excluded(fixture_vacancy("1", "Python backend", "apply"))
