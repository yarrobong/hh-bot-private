from __future__ import annotations

import argparse
import json
import os
import re
import socket
import tempfile
from dataclasses import dataclass, field
from html import unescape
from typing import Any, Protocol

from . import apply_safety
from .utils.string import strip_tags

DECISIONS = {"apply", "skip", "needs_review", "malformed", "already_processed"}
RETRYABLE_API = {"429", "500", "502", "503", "timeout", "connection"}

HARD_EXCLUDE_RE = re.compile(
    r"первая линия|1.?я линия|техподдержк|техническ[а-я ]+поддержк|"
    r"call.?center|колл.?центр|оператор|qa\b|aqa\b|тестировщик|"
    r"\b1с\b|1c\b|c\+\+|qt\b|embedded|встраиваем|stm32|микроконтрол|"
    r"преподавател|учитель|дет[еи]|школьник|продаж|холодн[ыех ]+звон|"
    r"маркетинг|smm|промоутер|амбассадор|производств|рабоч[а-я ]+специальност",
    re.I,
)
TARGET_RE = re.compile(
    r"python|django|backend|api|интеграц|автоматизац|ai|ии|llm|"
    r"react|javascript|frontend|fullstack|crm|bitrix24|битрикс24|"
    r"amocrm|amo.?crm|low.?code|no.?code|devops|linux|bash|sql|"
    r"аналитик данных|системн[а-я ]+аналитик|техническ[а-я ]+аналитик|"
    r"администратор сайта|техническ[а-я ]+администратор|java|c#|php",
    re.I,
)
JUNIOR_RE = re.compile(r"junior|стаж[её]р|trainee|обучени|без опыта|noexperience", re.I)
SENIORITY_EXCLUDE_RE = re.compile(r"\bmiddle\b|\bsenior\b|\blead\b|ведущ|тимлид|архитектор", re.I)
CONTROL_MARKER_RE = apply_safety.CONTROL_MARKER_RE
EKB_AREAS = {"екатеринбург", "ekaterinburg"}
REMOTE_MARKERS = {"remote", "удаленная", "удалённая", "удаленно", "удалённо"}
OFFICE_MARKERS = {
    "fullDay",
    "shift",
    "flexible",
    "flyInFlyOut",
    "на месте работодателя",
    "офис",
    "гибрид",
    "hybrid",
}


class AIEvaluator(Protocol):
    def evaluate(self, vacancy: "NormalizedVacancy") -> str:
        ...


@dataclass(frozen=True)
class NormalizedVacancy:
    id: str
    title: str
    employer: str
    area: str
    address_city: str
    schedule: str
    work_format: str
    experience: str
    employment: str
    professional_roles: tuple[str, ...]
    salary_from: int | None
    salary_to: int | None
    salary_unknown: bool
    url: str
    text: str
    archived: bool
    relations: tuple[str, ...]
    has_test: bool
    response_url: str
    raw: dict[str, Any]

    @property
    def display_format(self) -> str:
        return self.work_format or self.schedule or "unknown"


@dataclass
class Decision:
    vacancy_id: str
    title: str
    decision: str
    reason: str
    salary_unknown: bool = False
    posted: bool = False
    would_apply: bool = False


@dataclass
class ApplyMetrics:
    found: int = 0
    normalized: int = 0
    malformed: int = 0
    locally_rejected: int = 0
    ai_rejected: int = 0
    needs_review: int = 0
    duplicate: int = 0
    would_apply: int = 0
    attempted: int = 0
    successfully_sent: int = 0
    already_applied: int = 0
    retryable_error: int = 0
    terminal_error: int = 0

    @property
    def actual_sent(self) -> int:
        return self.successfully_sent

    def as_dict(self) -> dict[str, int]:
        return {
            "found": self.found,
            "normalized": self.normalized,
            "malformed": self.malformed,
            "locally_rejected": self.locally_rejected,
            "ai_rejected": self.ai_rejected,
            "needs_review": self.needs_review,
            "duplicate": self.duplicate,
            "would_apply": self.would_apply,
            "attempted": self.attempted,
            "successfully_sent": self.successfully_sent,
            "already_applied": self.already_applied,
            "retryable_error": self.retryable_error,
            "terminal_error": self.terminal_error,
            "actual_sent": self.actual_sent,
        }


@dataclass
class PipelineResult:
    decisions: list[Decision] = field(default_factory=list)
    metrics: ApplyMetrics = field(default_factory=ApplyMetrics)
    stopped_reason: str = ""


class AuthorizationError(RuntimeError):
    pass


class FakeAIEvaluator:
    def __init__(self, responses: dict[str, str | Exception] | None = None):
        self.responses = responses or {}

    def evaluate(self, vacancy: NormalizedVacancy) -> str:
        result = self.responses.get(vacancy.id, '{"decision":"apply"}')
        if isinstance(result, Exception):
            raise result
        return result


class FakeApplyTransport:
    def __init__(self, outcomes: dict[str, str] | None = None):
        self.outcomes = outcomes or {}
        self.posts: list[tuple[str, str, str]] = []
        self.attempts: dict[str, int] = {}

    def post_apply(self, vacancy: NormalizedVacancy, resume_id: str, letter: str) -> str:
        self.posts.append((vacancy.id, resume_id, letter))
        self.attempts[vacancy.id] = self.attempts.get(vacancy.id, 0) + 1
        outcome = self.outcomes.get(vacancy.id, "201")
        if outcome in {"200", "201", "empty"}:
            return "sent"
        if outcome == "409":
            return "already_applied"
        if outcome == "401":
            raise AuthorizationError("HH API authorization failed with HTTP 401")
        if outcome in RETRYABLE_API:
            return "retryable_error"
        if outcome in {"400", "403", "404", "malformed_json"}:
            return "terminal_error"
        return "terminal_error"


def text_value(value: Any) -> str:
    if value is None:
        return ""
    return strip_tags(unescape(str(value))).strip()


def normalize_vacancy(raw: dict[str, Any]) -> tuple[NormalizedVacancy | None, str]:
    if not isinstance(raw, dict):
        return None, "not_json_object"

    vacancy_id = str(raw.get("id") or "").strip()
    url = str(raw.get("alternate_url") or "").strip()
    if not vacancy_id and url:
        match = re.search(r"/vacancy/(\d+)", url)
        if match:
            vacancy_id = match.group(1)
    if not vacancy_id:
        return None, "missing_id"
    if url and not re.search(r"/vacancy/\d+", url):
        return None, "unexpected_url"

    salary = raw.get("salary") if isinstance(raw.get("salary"), dict) else None
    area = raw.get("area") if isinstance(raw.get("area"), dict) else {}
    employer = raw.get("employer") if isinstance(raw.get("employer"), dict) else {}
    snippet = raw.get("snippet") if isinstance(raw.get("snippet"), dict) else {}
    schedule = raw.get("schedule") if isinstance(raw.get("schedule"), dict) else {}
    experience = raw.get("experience") if isinstance(raw.get("experience"), dict) else {}
    address = raw.get("address") if isinstance(raw.get("address"), dict) else {}
    employment = raw.get("employment") if isinstance(raw.get("employment"), dict) else {}
    work_format_raw = raw.get("work_format")
    work_formats: list[str] = []
    if isinstance(work_format_raw, list):
        work_formats = [
            text_value(item.get("id") or item.get("name"))
            for item in work_format_raw
            if isinstance(item, dict)
        ]
    elif isinstance(work_format_raw, dict):
        work_formats = [
            text_value(work_format_raw.get("id") or work_format_raw.get("name"))
        ]
    professional_roles_raw = raw.get("professional_roles")
    professional_roles: list[str] = []
    if isinstance(professional_roles_raw, list):
        professional_roles = [
            text_value(item.get("name") or item.get("id"))
            for item in professional_roles_raw
            if isinstance(item, dict)
        ]
    text = "\n".join(
        filter(
            None,
            [
                text_value(raw.get("name")),
                text_value(snippet.get("requirement")),
                text_value(snippet.get("responsibility")),
                text_value(raw.get("description")),
            ],
        )
    )
    return (
        NormalizedVacancy(
            id=vacancy_id,
            title=text_value(raw.get("name")) or f"vacancy {vacancy_id}",
            employer=text_value(employer.get("name")),
            area=text_value(area.get("name")),
            address_city=text_value(address.get("city")),
            schedule=text_value(schedule.get("id") or schedule.get("name")),
            work_format=", ".join(filter(None, work_formats)),
            experience=text_value(experience.get("id") or experience.get("name")),
            employment=text_value(employment.get("id") or employment.get("name")),
            professional_roles=tuple(filter(None, professional_roles)),
            salary_from=salary.get("from") if salary else None,
            salary_to=salary.get("to") if salary else None,
            salary_unknown=salary is None,
            url=url or f"https://hh.ru/vacancy/{vacancy_id}",
            text=text,
            archived=bool(raw.get("archived")),
            relations=tuple(str(x) for x in raw.get("relations") or []),
            has_test=bool(raw.get("has_test") or raw.get("response_letter_required")),
            response_url=str(raw.get("response_url") or ""),
            raw=raw,
        ),
        "ok",
    )


def local_decision(vacancy: NormalizedVacancy) -> tuple[str, str]:
    return VacancyEvaluator().evaluate(vacancy)


class VacancyEvaluator:
    def evaluate(self, vacancy: NormalizedVacancy) -> tuple[str, str]:
        haystack = "\n".join(
            filter(
                None,
                [
                    vacancy.title,
                    vacancy.employer,
                    vacancy.area,
                    vacancy.address_city,
                    vacancy.schedule,
                    vacancy.work_format,
                    vacancy.experience,
                    vacancy.employment,
                    " ".join(vacancy.professional_roles),
                    vacancy.text,
                ],
            )
        )
        low = haystack.lower()
        geography_decision = self._evaluate_geography(vacancy, low)
        if vacancy.archived:
            return "already_processed", "archived"
        if vacancy.relations:
            if "got_rejection" in vacancy.relations:
                return "already_processed", "employer_rejection"
            return "already_processed", "already_has_relation"
        if geography_decision:
            hard_reason = self._hard_exclusion_reason(haystack)
            if geography_decision[0] == "skip" and hard_reason:
                return "skip", f"{geography_decision[1]}+{hard_reason}"
            return geography_decision
        hard_reason = self._hard_exclusion_reason(haystack)
        if hard_reason:
            return "skip", hard_reason
        if re.search(r"переезд|релокац", low) and "екатеринбург" not in low:
            return "skip", "relocation_not_ekb"
        if vacancy.salary_to is not None and vacancy.salary_to < 30000:
            return "skip", "salary_below_minimum"
        if vacancy.has_test or vacancy.response_url or re.search(
            r"анкета|тестов[а-я ]+задани|google forms|внешн[а-я ]+сайт", low
        ):
            return "needs_review", "questions_or_external_form"
        if not vacancy.text:
            return "needs_review", "insufficient_data"
        if re.search(r"\b(java|c#|php)\b", low) and (
            SENIORITY_EXCLUDE_RE.search(low) or not JUNIOR_RE.search(low)
        ):
            return "skip", "non_junior_java_csharp_php"
        if TARGET_RE.search(haystack):
            return "apply", "profile_match"
        if vacancy.text.strip() == vacancy.title:
            return "needs_review", "insufficient_data"
        return "skip", "profile_mismatch"

    def _evaluate_geography(
        self, vacancy: NormalizedVacancy, low: str
    ) -> tuple[str, str] | None:
        area = vacancy.area.strip().lower()
        address_city = vacancy.address_city.strip().lower()
        fmt = f"{vacancy.schedule} {vacancy.work_format}".strip().lower()
        is_remote = any(marker in fmt for marker in REMOTE_MARKERS)
        is_hybrid = "гибрид" in fmt or "hybrid" in fmt
        is_office = bool(fmt) and not is_remote
        is_ekb = area in EKB_AREAS or address_city in EKB_AREAS

        if is_remote and not is_hybrid:
            return None
        if is_hybrid and not is_ekb:
            return "skip", "office_or_hybrid_not_ekb"
        if is_office and not is_ekb:
            return "skip", "office_not_ekb"
        if not fmt and not area:
            return "needs_review", "unknown_location_or_format"
        if not fmt and area and not is_ekb and "удален" not in low and "удалён" not in low:
            return "needs_review", "unknown_work_format"
        return None

    def _hard_exclusion_reason(self, haystack: str) -> str:
        low = haystack.lower()
        if re.search(r"преподавател|учитель|педагог|дет[еи]|школьник", low):
            return "teaching_children"
        if re.search(r"первая линия|1.?я линия|техподдержк|техническ[а-я ]+поддержк|helpdesk|оператор|call.?center|колл.?центр", low):
            return "support_or_call_center"
        if re.search(r"\bqa\b|\baqa\b|тестировщик|тестировани", low):
            return "qa"
        if re.search(r"продаж|холодн[ыех ]+звон", low):
            return "sales"
        if re.search(r"маркетинг|smm", low):
            return "marketing"
        if re.search(r"\b1с\b|1c\b", low):
            return "one_c"
        if re.search(r"c\+\+|qt\b|qml", low):
            return "cpp_qt"
        if re.search(r"embedded|встраиваем|stm32|микроконтрол", low):
            return "embedded"
        if re.search(r"производств|рабоч[а-я ]+специальност", low):
            return "production"
        if re.search(r"data scientist|data science|machine learning|recsys|ml engineer|ml-инженер", low):
            return "role_mismatch"
        return ""


def format_decision_line(prefix: str, vacancy: NormalizedVacancy, reason: str) -> str:
    return (
        f"{prefix} vacancy_id={vacancy.id} title={vacancy.title!r} "
        f"area={vacancy.area or 'unknown'} format={vacancy.display_format} "
        f"reason={reason} url={vacancy.url}"
    )


def parse_ai_decision(response: str) -> tuple[str, str]:
    text = (response or "").strip()
    if not text:
        return "needs_review", "ai_empty"
    if text in {"apply", "skip", "needs_review"}:
        return text, "ai_plain"
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return "needs_review", "ai_invalid_json"
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return "needs_review", "ai_invalid_json"
    decision = str(data.get("decision") or "").strip()
    suitable = data.get("suitable")
    if decision not in {"apply", "skip", "needs_review"}:
        return "needs_review", "ai_unknown_marker"
    if decision == "apply" and suitable is False:
        return "needs_review", "ai_contradictory"
    return decision, "ai_ok"


def build_cover_letter(vacancy: NormalizedVacancy) -> str:
    place = "удаленному формату" if vacancy.schedule == "remote" else "работе в Екатеринбурге"
    return (
        f"Здравствуйте. Вакансия «{vacancy.title}» мне интересна: могу быть полезен "
        f"в задачах с Python, Django, SQL, интеграциями, автоматизацией и AI-инструментами. "
        f"Готов обсудить формат и быстро выйти на связь по {place}."
    )


def run_apply_pipeline(
    vacancies: list[dict[str, Any]],
    *,
    resume_id: str = "resume-1",
    ai: AIEvaluator | None = None,
    transport: FakeApplyTransport | None = None,
    owner: str = "local_apply_test",
) -> PipelineResult:
    ai = ai or FakeAIEvaluator()
    transport = transport or FakeApplyTransport()
    result = PipelineResult()
    result.metrics.found = len(vacancies)
    seen_in_run: set[str] = set()

    for raw in vacancies:
        normalized, reason = normalize_vacancy(raw)
        if not normalized:
            result.metrics.malformed += 1
            result.decisions.append(Decision("", "", "malformed", reason))
            continue

        result.metrics.normalized += 1
        if normalized.id in seen_in_run:
            result.metrics.duplicate += 1
            result.decisions.append(
                Decision(
                    normalized.id,
                    normalized.title,
                    "already_processed",
                    "duplicate_in_run",
                    normalized.salary_unknown,
                )
            )
            continue
        seen_in_run.add(normalized.id)

        existing = apply_safety.claim_status(normalized.id, resume_id)
        if apply_safety.terminal_status(existing):
            result.metrics.duplicate += 1
            result.decisions.append(
                Decision(
                    normalized.id,
                    normalized.title,
                    "already_processed",
                    existing or "duplicate",
                    normalized.salary_unknown,
                )
            )
            continue

        decision, reason = local_decision(normalized)
        if decision != "apply":
            if decision == "needs_review":
                result.metrics.needs_review += 1
            elif decision == "already_processed":
                result.metrics.duplicate += 1
            else:
                result.metrics.locally_rejected += 1
            claim = apply_safety.try_claim(
                normalized.id, resume_id, owner=owner, stage=decision
            )
            if claim.acquired:
                status = {
                    "skip": "locally_rejected",
                    "needs_review": "needs_review",
                    "already_processed": "already_applied",
                }[decision]
                apply_safety.update_claim(normalized.id, resume_id, status, reason=reason)
            result.decisions.append(
                Decision(
                    normalized.id,
                    normalized.title,
                    decision,
                    reason,
                    normalized.salary_unknown,
                )
            )
            continue

        try:
            ai_decision, ai_reason = parse_ai_decision(ai.evaluate(normalized))
        except Exception as ex:
            ai_decision, ai_reason = "needs_review", f"ai_exception:{type(ex).__name__}"
        if ai_decision != "apply":
            if ai_decision == "skip":
                result.metrics.ai_rejected += 1
                status = "ai_rejected"
            else:
                result.metrics.needs_review += 1
                status = "needs_review"
            claim = apply_safety.try_claim(
                normalized.id, resume_id, owner=owner, stage=status
            )
            if claim.acquired:
                apply_safety.update_claim(normalized.id, resume_id, status, reason=ai_reason)
            result.decisions.append(
                Decision(
                    normalized.id,
                    normalized.title,
                    ai_decision,
                    ai_reason,
                    normalized.salary_unknown,
                )
            )
            continue

        letter = build_cover_letter(normalized)
        guard = apply_safety.guard_apply_post(
            normalized.id, resume_id, letter, stage="local_apply_pipeline"
        )
        if not guard.allowed:
            if guard.log_code == "WOULD_APPLY":
                result.metrics.would_apply += 1
                result.decisions.append(
                    Decision(
                        normalized.id,
                        normalized.title,
                        "apply",
                        "would_apply",
                        normalized.salary_unknown,
                        would_apply=True,
                    )
                )
            else:
                result.metrics.terminal_error += 1
                result.decisions.append(
                    Decision(
                        normalized.id,
                        normalized.title,
                        "skip",
                        guard.reason,
                        normalized.salary_unknown,
                    )
                )
            continue

        claim = apply_safety.try_claim(
            normalized.id, resume_id, owner=owner, stage="post_apply"
        )
        if not claim.acquired:
            result.metrics.duplicate += 1
            result.decisions.append(
                Decision(
                    normalized.id,
                    normalized.title,
                    "already_processed",
                    claim.status,
                    normalized.salary_unknown,
                )
            )
            continue

        result.metrics.attempted += 1
        try:
            api_result = transport.post_apply(normalized, resume_id, letter)
        except AuthorizationError:
            apply_safety.release_retryable_claim(
                normalized.id, resume_id, reason="unauthorized"
            )
            raise
        if api_result == "sent":
            result.metrics.successfully_sent += 1
            apply_safety.update_claim(normalized.id, resume_id, "sent")
            result.decisions.append(
                Decision(normalized.id, normalized.title, "apply", "sent", posted=True)
            )
        elif api_result == "already_applied":
            result.metrics.already_applied += 1
            apply_safety.update_claim(normalized.id, resume_id, "already_applied")
            result.decisions.append(
                Decision(normalized.id, normalized.title, "already_processed", "already_applied")
            )
        elif api_result == "retryable_error":
            result.metrics.retryable_error += 1
            apply_safety.release_retryable_claim(
                normalized.id, resume_id, reason="retryable_api_error"
            )
            result.decisions.append(
                Decision(normalized.id, normalized.title, "skip", "retryable_error")
            )
        else:
            result.metrics.terminal_error += 1
            apply_safety.update_claim(normalized.id, resume_id, "terminal_error")
            result.decisions.append(
                Decision(normalized.id, normalized.title, "skip", "terminal_error")
            )

    return result


def install_network_block() -> None:
    class BlockedSocket(socket.socket):
        def connect(self, address):  # type: ignore[no-untyped-def]
            raise RuntimeError("network disabled in local fixture harness")

    socket.socket = BlockedSocket  # type: ignore[assignment]


def fixture_vacancy(
    vid: str,
    title: str,
    expected: str,
    *,
    area: str = "Россия",
    schedule: str = "remote",
    salary: dict[str, Any] | None = None,
    text: str = "Python Django SQL API интеграции",
    relations: list[str] | None = None,
    archived: bool = False,
    has_test: bool = False,
    response_url: str = "",
    url: str | None = None,
    work_format: str = "",
    address_city: str = "",
    professional_roles: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": vid,
        "name": title,
        "alternate_url": url if url is not None else f"https://hh.ru/vacancy/{vid}",
        "area": {"name": area} if area else None,
        "employer": {"name": f"Employer {vid}"},
        "salary": salary,
        "schedule": {"id": schedule},
        "work_format": [{"name": work_format}] if work_format else [],
        "address": {"city": address_city} if address_city else None,
        "experience": {"id": "noExperience"},
        "employment": {"id": "full"},
        "professional_roles": [
            {"name": role} for role in (professional_roles or [])
        ],
        "snippet": {"requirement": text, "responsibility": text},
        "relations": relations or [],
        "archived": archived,
        "has_test": has_test,
        "response_url": response_url,
        "expected_decision": expected,
    }


def fixture_matrix() -> list[dict[str, Any]]:
    data = [
        fixture_vacancy("1001", "Junior Python Django developer", "apply", salary={"from": 45000, "to": None}),
        fixture_vacancy("1002", "Backend Python API", "apply", salary={"from": 80000, "to": None}),
        fixture_vacancy("1003", "Интегратор CRM amoCRM", "apply", text="CRM API интеграции автоматизация"),
        fixture_vacancy("1004", "AI automation специалист", "apply", text="LLM AI automation Python"),
        fixture_vacancy("1005", "Frontend React junior", "apply", text="React JavaScript API"),
        fixture_vacancy("1006", "Fullstack Django React", "apply", text="Python React SQL"),
        fixture_vacancy("1007", "Junior DevOps Linux", "apply", text="Linux Bash Python автоматизация"),
        fixture_vacancy("1008", "SQL analyst junior", "apply", text="SQL аналитик данных junior"),
        fixture_vacancy("1009", "Системный аналитик junior", "apply", text="API SQL технический аналитик"),
        fixture_vacancy("1010", "Технический администратор сайта", "apply", text="сайт SQL автоматизация"),
        fixture_vacancy("1011", "Java junior обучение", "apply", text="Java junior обучение API"),
        fixture_vacancy("1012", "PHP trainee developer", "apply", text="PHP trainee backend"),
        fixture_vacancy("1013", "Python developer Екатеринбург", "apply", area="Екатеринбург", schedule="fullDay"),
        fixture_vacancy("1014", "Bitrix24 интегратор", "apply", text="Bitrix24 CRM API"),
        fixture_vacancy("1015", "No-code automation", "apply", text="low-code no-code CRM"),
        fixture_vacancy("2001", "Специалист первой линии поддержки", "skip", text="первая линия техподдержка"),
        fixture_vacancy("2002", "Оператор call center", "skip", text="call center холодные звонки"),
        fixture_vacancy("2003", "QA tester", "skip", text="QA AQA тест-кейсы"),
        fixture_vacancy("2004", "1С разработчик", "skip", text="1С предприятие"),
        fixture_vacancy("2005", "C++ Qt developer", "skip", text="C++ Qt embedded"),
        fixture_vacancy("2006", "Преподаватель программирования детям", "skip", text="работа с детьми школа"),
        fixture_vacancy("2007", "Менеджер по продажам", "skip", text="продажи холодные звонки"),
        fixture_vacancy("2008", "SMM маркетолог", "skip", text="маркетинг SMM"),
        fixture_vacancy("2009", "Промоутер", "skip", text="амбассадор промо"),
        fixture_vacancy("2010", "Рабочий на производство", "skip", text="производство рабочая специальность"),
        fixture_vacancy("2011", "Backend Java Middle", "skip", text="Java Spring middle"),
        fixture_vacancy("2012", "Python офис Москва", "skip", area="Москва", schedule="fullDay", text="офис Москва Python"),
        fixture_vacancy("2013", "Python с переездом в Санкт-Петербург", "skip", text="обязательный переезд Санкт-Петербург Python"),
        fixture_vacancy("2014", "Низкая зарплата Python", "skip", salary={"from": 15000, "to": 25000}),
        *real_dry_run_regression_vacancies(),
        fixture_vacancy("3001", "Python с анкетой", "needs_review", response_url="https://hh.ru/form"),
        fixture_vacancy("3002", "Python с тестовым заданием", "needs_review", has_test=True),
        fixture_vacancy("3003", "Python external form", "needs_review", text="Python google forms внешний сайт"),
        fixture_vacancy("3004", "Неполное описание", "needs_review", text=""),
        fixture_vacancy("3005", "Зарплата не указана Python", "apply", salary=None),
        fixture_vacancy("4001", "Уже откликались", "already_processed", relations=["negotiations"]),
        fixture_vacancy("4002", "Работодатель отказал", "already_processed", relations=["got_rejection"]),
        fixture_vacancy("4003", "Архивная Python", "already_processed", archived=True),
        fixture_vacancy("1001", "Дубль Junior Python Django developer", "already_processed"),
        fixture_vacancy("", "Без id", "malformed"),
        fixture_vacancy("5001", "Неожиданный URL", "malformed", url="https://example.test/not-a-vacancy"),
        {
            "id": "5002",
            "name": "",
            "alternate_url": "https://hh.ru/vacancy/5002",
            "salary": None,
            "area": None,
            "employer": None,
            "snippet": None,
            "schedule": None,
            "experience": None,
            "expected_decision": "needs_review",
        },
        {
            "name": "ID только в URL",
            "alternate_url": "https://hh.ru/vacancy/5003",
            "salary": None,
            "area": {"name": "Россия"},
            "employer": {"name": "No ID"},
            "snippet": {"requirement": "<b>Python</b>", "responsibility": None},
            "schedule": {"id": "remote"},
            "experience": {"id": "unknown_enum"},
            "expected_decision": "apply",
        },
    ]
    return data


def real_dry_run_regression_vacancies() -> list[dict[str, Any]]:
    return [
        fixture_vacancy(
            "135311616",
            "Junior-разработчик / вайбкодер",
            "skip",
            area="Краснодар",
            schedule="fullDay",
            work_format="Гибрид",
            text="Python Django junior. Периодически необходимо работать на территории работодателя.",
        ),
        fixture_vacancy(
            "135389858",
            "Junior LLM Engineer",
            "skip",
            area="Казань",
            schedule="fullDay",
            work_format="Гибрид",
            text="LLM Python junior, гибридный формат работы.",
        ),
        fixture_vacancy(
            "135397712",
            "Младший Fullstack разработчик",
            "skip",
            area="Симферополь",
            schedule="fullDay",
            work_format="На месте работодателя",
            text="Fullstack JavaScript Python, работа на месте работодателя.",
        ),
        fixture_vacancy(
            "135364012",
            "Data Scientist junior",
            "skip",
            area="Нижний Новгород",
            schedule="fullDay",
            work_format="Офис",
            text="Machine Learning RecSys data science Python.",
            professional_roles=["Data Scientist"],
        ),
        fixture_vacancy(
            "135435089",
            "Преподаватель по информатике",
            "skip",
            area="Казань",
            schedule="fullDay",
            work_format="На месте работодателя",
            text="Преподаватель информатики, педагог, работа с детьми.",
            professional_roles=["Преподаватель"],
        ),
    ]


SCENARIOS = {
    "normal": lambda: fixture_matrix(),
    "malformed": lambda: fixture_matrix()[-4:],
    "api-errors": lambda: [
        fixture_vacancy("6001", "API success 200 Python", "apply"),
        fixture_vacancy("6002", "API already applied Python", "already_processed"),
        fixture_vacancy("6003", "API 429 Python", "skip"),
        fixture_vacancy("6004", "API 500 Python", "skip"),
        fixture_vacancy("6005", "API 400 Python", "skip"),
    ],
    "duplicates": lambda: [
        fixture_vacancy("7001", "Duplicate Python A", "apply"),
        fixture_vacancy("7001", "Duplicate Python B", "already_processed"),
    ],
}


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="normal")
    parser.add_argument("--all", action="store_true")
    ns = parser.parse_args(argv)
    print("LOCAL FIXTURE MODE — NETWORK DISABLED — REAL APPLICATIONS IMPOSSIBLE")
    install_network_block()
    scenarios = sorted(SCENARIOS) if ns.all else [ns.scenario]
    ok = True
    for scenario in scenarios:
        if scenario == "api-errors":
            os.environ.pop("HH_APPLY_DRY_RUN", None)
            os.environ["HH_APPLY_SEND_ENABLED"] = "1"
        else:
            os.environ["HH_APPLY_DRY_RUN"] = "1"
            os.environ.pop("HH_APPLY_SEND_ENABLED", None)
        with tempfile.TemporaryDirectory(prefix=f"hh-apply-{scenario}-") as tmp:
            os.environ["HH_BOT_BASE"] = tmp
            scenario_vacancies = SCENARIOS[scenario]()
            result = run_apply_pipeline(
                scenario_vacancies,
                transport=FakeApplyTransport(
                    {
                        "6001": "200",
                        "6002": "409",
                        "6003": "429",
                        "6004": "500",
                        "6005": "400",
                    }
                ),
            )
        print(f"\nSCENARIO {scenario}")
        expected_sequence = [
            str(raw.get("expected_decision") or "") for raw in scenario_vacancies
        ]
        for index, decision in enumerate(result.decisions):
            expected = expected_sequence[index] if index < len(expected_sequence) else ""
            marker = "OK" if not expected or expected == decision.decision else "BAD"
            ok = ok and marker == "OK"
            print(
                f"{marker:3} {decision.vacancy_id or '-':>6} "
                f"{decision.decision:17} {decision.reason}"
            )
        print("METRICS", json.dumps(result.metrics.as_dict(), ensure_ascii=False, sort_keys=True))
        if scenario != "api-errors" and result.metrics.actual_sent != 0:
            print("BAD safety invariant: actual_sent must be 0 in dry-run/default-disabled mode")
            ok = False
    return 0 if ok else 1
