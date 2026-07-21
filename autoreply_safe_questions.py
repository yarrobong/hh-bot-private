import json
import os
import re
import sys
import subprocess
from pathlib import Path
from datetime import datetime

BASE = Path(os.environ.get("HH_BOT_BASE", "/opt/hh-bot"))
STATE = BASE / "state"
SEEN_FILE = STATE / "autoreply_safe_seen.json"
REVIEW_FILE = STATE / "backfill_review.json"
ASK_DIR = STATE / "ask_requests"
ANS_DIR = STATE / "human_answers"

STATE.mkdir(parents=True, exist_ok=True)
ASK_DIR.mkdir(parents=True, exist_ok=True)
ANS_DIR.mkdir(parents=True, exist_ok=True)

TOOL = os.environ.get(
    "HH_APPLICANT_TOOL_BIN",
    str(BASE / "venv" / "bin" / "hh-applicant-tool"),
)

TERMINAL = {"sent", "disabled_by_employer", "test_ignored", "ignored"}

BAD_VACANCY = re.compile(
    r"преподав|педагог|учитель|репетитор|школ|дет|шахмат|"
    r"продаж|менеджер по продаж|маркетинг|smm|арбитраж|"
    r"техподдерж|техническ.*поддерж|1.?линия|support|"
    r"qa|aqa|тестировщик|тестировани|"
    r"1с|c\+\+|qt|bim|revit|autocad|робототех|embedded|arduino|stm32|"
    r"рабочий|разнорабочий|слесарь|производств|амбассадор|промо|флаер",
    re.I,
)

REVIEW_PATTERNS = re.compile(
    r"telegram|телеграм|@\w+|http|https|ссылк|анкета|заполн|тестов|"
    r"позвон|созвон|номер|телефон|когда удобно|выберите время|выбрать время|"
    r"пройдите|зарегистр",
    re.I,
)

NO_REPLY = re.compile(
    r"спасибо за отклик|рассмотрим резюме|мы свяжемся|отказ|не готовы|"
    r"вакансия закрыта|приглашение отменено|благодарим за интерес",
    re.I,
)

def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def call_api(args):
    res = subprocess.run([TOOL, "call-api", *args], text=True, capture_output=True)
    raw = res.stdout.strip()
    if raw.startswith("{"):
        try:
            return json.loads(raw)
        except Exception:
            pass
    if res.returncode != 0:
        print("API_ERROR:", " ".join(args), (res.stderr or res.stdout)[:500])
    return None

def post_message(nid, msg):
    res = subprocess.run(
        [TOOL, "call-api", "-m", "POST", f"/negotiations/{nid}/messages", f"message={msg}"],
        text=True,
        capture_output=True,
    )
    return res.returncode, res.stdout.strip(), res.stderr.strip()

def msg_key(nid, msg):
    mid = msg.get("id") or (msg.get("created_at", "") + ":" + str(abs(hash(msg.get("text") or ""))))
    return f"{nid}:{mid}"

def add_review(item):
    data = load_json(REVIEW_FILE, [])
    key = (str(item.get("negotiation_id")), item.get("text") or "")
    for old in data:
        if (str(old.get("negotiation_id")), old.get("text") or "") == key:
            return
    data.append(item)
    save_json(REVIEW_FILE, data)

def has_pending_human_flow(nid):
    for path in (ASK_DIR / f"{nid}.json", ANS_DIR / f"{nid}.json"):
        data = load_json(path, {})
        status = data.get("status")
        if data and status not in TERMINAL:
            return True
    return False

def answer_for(text, vacancy):
    t = (text or "").lower()

    if "sso" in t or "saml" in t or "oidc" in t:
        return (
            "Здравствуйте! Прямого production-опыта настройки SSO через SAML или OIDC у меня не было, "
            "но понимаю общую схему SSO: IdP/SP, редиректы, токены/claims, callback, роли и права доступа. "
            "Есть опыт работы с Python, Linux, автоматизацией, API и интеграциями. "
            "Смогу быстро разобраться с конкретной реализацией и документацией."
        )

    if "offboarding" in t or "оффбординг" in t:
        return (
            "Здравствуйте! Да, есть опыт автоматизации внутренних процессов с помощью Python и скриптов. "
            "Именно production-процедуру offboarding я не настраивал, но понимаю логику: отключение доступов, "
            "обновление статусов, уведомления, работа с API и журналирование действий. "
            "Смогу быстро разобраться в вашей схеме и документации."
        )

    if "англий" in t or "english" in t:
        if "зарплат" in t or "оклад" in t:
            return (
                "Здравствуйте! Английский — на уровне чтения технической документации и базовой письменной коммуникации. "
                "Минимально комфортный уровень зарплаты на старте — от 30 000 ₽, дальше готов обсуждать по задачам и формату работы."
            )
        return (
            "Здравствуйте! Английский — на уровне чтения технической документации и базовой письменной коммуникации. "
            "Для рабочих задач с документацией и инструментами этого достаточно, разговорный уровень готов подтягивать."
        )

    if "зарплат" in t or "оклад" in t or "сколько" in t and "получ" in t:
        return (
            "Здравствуйте! Минимально комфортный уровень зарплаты на старте — от 30 000 ₽. "
            "Дальше готов обсуждать по задачам, формату работы и зоне ответственности."
        )

    if "начнем" in t or "начнём" in t:
        return "Здравствуйте! Да, готов ответить на вопросы."

    if "опыт" in t or "расскаж" in t or "готовы" in t or "интерес" in t:
        return (
            "Здравствуйте! Есть практический опыт с Python, Django, SQL, Linux, Git, API, интеграциями, "
            "автоматизацией процессов, CRM и AI-инструментами. "
            "Основной интерес — backend, техническая автоматизация, интеграции и внутренние IT-инструменты. "
            "Готов обсудить задачи подробнее."
        )

    return None

def get_last_messages():
    result = []
    for page in range(0, 3):
        data = call_api(["/negotiations", "status=active", f"page={page}", "per_page=100"])
        if not data:
            continue

        items = data.get("items", [])
        if not items:
            break

        for it in items:
            nid = str(it.get("id") or "")
            state = (it.get("state") or {}).get("id") or ""
            if state not in {"response", "interview"}:
                continue
            if has_pending_human_flow(nid):
                continue

            v = it.get("vacancy") or {}
            emp = it.get("employer") or v.get("employer") or {}
            vacancy = v.get("name") or ""
            employer = emp.get("name") or ""

            msgs = call_api([f"/negotiations/{nid}/messages", "page=0", "per_page=20"])
            if not msgs:
                continue

            arr = sorted(msgs.get("items", []), key=lambda x: x.get("created_at") or "")
            if not arr:
                continue

            last = arr[-1]
            author = (last.get("author") or {}).get("participant_type")
            if author != "employer":
                continue

            result.append((nid, vacancy, employer, state, last))

    return result

def main():
    seen = load_json(SEEN_FILE, {})
    bootstrap = "--bootstrap" in sys.argv

    sent = 0
    reviewed = 0
    skipped = 0
    boot = 0

    for nid, vacancy, employer, _state, last in get_last_messages():
        text = last.get("text") or ""
        k = msg_key(nid, last)

        if k in seen:
            skipped += 1
            continue

        if bootstrap:
            seen[k] = {"status": "bootstrapped", "at": datetime.now().isoformat()}
            boot += 1
            continue

        full_vacancy = f"{vacancy} {employer}"

        if NO_REPLY.search(text):
            seen[k] = {"status": "ignored_no_reply", "at": datetime.now().isoformat()}
            skipped += 1
            continue

        if BAD_VACANCY.search(full_vacancy):
            add_review({
                "negotiation_id": nid,
                "vacancy": vacancy,
                "created_at": last.get("created_at"),
                "reason": "bad_or_questionable_vacancy",
                "text": text,
            })
            seen[k] = {"status": "review_bad_vacancy", "at": datetime.now().isoformat()}
            reviewed += 1
            continue

        if REVIEW_PATTERNS.search(text):
            add_review({
                "negotiation_id": nid,
                "vacancy": vacancy,
                "created_at": last.get("created_at"),
                "reason": "needs_human_decision",
                "text": text,
            })
            seen[k] = {"status": "review_external_or_manual", "at": datetime.now().isoformat()}
            reviewed += 1
            continue

        msg = answer_for(text, vacancy)

        if not msg:
            add_review({
                "negotiation_id": nid,
                "vacancy": vacancy,
                "created_at": last.get("created_at"),
                "reason": "unknown_question",
                "text": text,
            })
            seen[k] = {"status": "review_unknown", "at": datetime.now().isoformat()}
            reviewed += 1
            continue

        code, out, err = post_message(nid, msg)

        if code == 0:
            print("AUTO_SENT:", nid, "|", vacancy)
            seen[k] = {"status": "sent", "at": datetime.now().isoformat(), "answer": msg}
            sent += 1
        else:
            print("SEND_ERROR:", nid, "|", vacancy, "|", (err or out)[:500])
            if "disabled_by_employer" in (err + out):
                seen[k] = {"status": "disabled_by_employer", "at": datetime.now().isoformat()}
                skipped += 1
            else:
                add_review({
                    "negotiation_id": nid,
                    "vacancy": vacancy,
                    "created_at": last.get("created_at"),
                    "reason": "send_error",
                    "text": text,
                    "error": (err or out)[:500],
                })
                reviewed += 1

    save_json(SEEN_FILE, seen)
    print(f"AUTO_REPLY_SAFE done | sent={sent} reviewed={reviewed} skipped={skipped} bootstrapped={boot}")

if __name__ == "__main__":
    main()
