import json
import os
import re
import subprocess
from pathlib import Path
from datetime import datetime, date

BASE = Path(os.environ.get("HH_BOT_BASE", "/opt/hh-bot"))
STATE_DIR = BASE / "state"
LOG_DIR = BASE / "logs"
STATE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

SEEN_FILE = STATE_DIR / "backfill_seen.json"
REVIEW_FILE = STATE_DIR / "backfill_review.json"
ASK_DIR = STATE_DIR / "ask_requests"
LOG_FILE = LOG_DIR / "backfill-watch.log"
TOOL = os.environ.get(
    "HH_APPLICANT_TOOL_BIN",
    str(BASE / "venv" / "bin" / "hh-applicant-tool"),
)

NTFY_TOPIC = "hh-yaroslav-7x29q-answer"
ASK_DIR.mkdir(parents=True, exist_ok=True)

seen = {}
if SEEN_FILE.exists():
    try:
        seen = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
    except Exception:
        seen = {}

def log(msg):
    line = f"{datetime.now().strftime('%F %T')} {msg}"
    print(line)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

def norm(s):
    return (s or "").replace("\xa0", " ").strip()

def call_api(args):
    res = subprocess.run(
        [TOOL, "call-api", *args],
        text=True,
        capture_output=True,
    )
    if res.returncode != 0:
        return None
    raw = res.stdout.strip()
    if not raw.startswith("{"):
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def is_past_offline_interview(text):
    # Ищем формат: Дата и время: 01.07 15:00
    m = re.search(r"Дата\s+и\s+время:\s*(\d{2})\.(\d{2})\s+\d{1,2}:\d{2}", text or "", re.I)
    if not m:
        return False
    day = int(m.group(1))
    month = int(m.group(2))
    year = datetime.now().year
    try:
        d = date(year, month, day)
    except Exception:
        return False
    return d < datetime.now().date()

def ntfy(text):
    if os.environ.get("HH_DISABLE_NTFY") == "1":
        return
    try:
        subprocess.run(
            [
                "curl",
                "-fsS",
                "-H", "Title: HH старые диалоги",
                "-H", "Priority: 4",
                "-d", text,
                f"https://ntfy.sh/{NTFY_TOPIC}",
            ],
            text=True,
            capture_output=True,
            timeout=15,
        )
    except Exception:
        pass

def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def append_review(item):
    data = load_json(REVIEW_FILE, [])
    key = (str(item.get("negotiation_id")), item.get("text") or "")
    for old in data:
        if (str(old.get("negotiation_id")), old.get("text") or "") == key:
            return
    data.append(item)
    save_json(REVIEW_FILE, data)

def save_ask_request(item):
    nid = str(item["negotiation_id"])
    reason = item["reason"]
    if reason == "possible_ai_answer":
        ask_text = (
            "Похоже, работодатель задал вопрос, на который можно ответить. "
            "Проверь контекст и напиши безопасный ответ."
        )
    else:
        ask_text = item["text"]
    save_json(
        ASK_DIR / f"{nid}.json",
        {
            "nid": nid,
            "vacancy": item.get("vacancy") or "",
            "employer": item.get("employer") or "",
            "ask_text": ask_text,
            "history": item.get("text") or "",
            "status": "waiting",
            "reason": reason,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        },
    )

NO_REPLY_PATTERNS = [
    r"к сожалению.*не готовы пригласить",
    r"не готовы пригласить вас",
    r"не можем предложить",
    r"будем рады получать ваши отклики",
    r"рассмотрим ваше резюме",
    r"если навыки.*подойдут.*свяжемся",
    r"работодатель.*отзыва.*рейтинг",
    r"изучите мнения тех",
    r"благодарю за ответы",
    r"представитель работодателя ознакомится",
    r"спасибо, всё записал",
    r"отклик зафиксирован",
    r"всё зафиксировал",
    r"передаю информацию работодателю",
    r"передаю информацию",
]

BAD_VACANCY_PATTERNS = [
    r"преподавател",
    r"педагог",
    r"учитель",
    r"репетитор",
    r"школ",
    r"дет[еи]",
    r"логист",
    r"продаж",
    r"маркетинг",
    r"1с",
    r"c\+\+",
    r"qt",
    r"bim",
    r"рабочий",
    r"разнорабочий",
    r"слесарь",
    r"кормовые",
    r"qa\\b",
    r"aqa\\b",
    r"тестировщик",
    r"тестировани",
    r"техподдерж",
    r"техническ.*поддерж",
    r"support",
    r"smm",
    r"арбитраж",
    r"холодн.*звон",
    r"колл.?центр",
]

ASK_HUMAN_PATTERNS = [
    r"telegram",
    r"телеграм",
    r"@\w+",
    r"позвон",
    r"номер",
    r"созвон",
    r"когда будет удобно",
    r"во сколько будет удобно",
    r"анкета",
    r"ссылка",
    r"https?://",
    r"тестовое",
    r"заполнить",
    r"приглашаем.*собеседование",
]

AUTO_ANSWER_PATTERNS = [
    r"опыт",
    r"расскажите",
    r"есть ли у вас",
    r"как вы",
    r"сколько",
    r"какими",
    r"готовы ли",
]

data = call_api(["/negotiations", "status=active", "page=0", "per_page=100"])
if not data:
    log("ERROR cannot load negotiations")
    raise SystemExit(1)

review = []
ignored = 0
errors = 0
dedup_texts = set()

for n in data.get("items", []):
    nid = str(n.get("id"))
    vacancy = norm((n.get("vacancy") or {}).get("name"))
    state = (n.get("state") or {}).get("id")

    if state not in {"response", "interview"}:
        continue

    msg_data = call_api([f"/negotiations/{nid}/messages", "page=0", "per_page=20"])
    if not msg_data:
        errors += 1
        continue

    items = msg_data.get("items") or []
    if not items:
        continue

    items = sorted(items, key=lambda m: m.get("created_at") or "")
    last = items[-1]

    author = (last.get("author") or {}).get("participant_type")
    text = norm(last.get("text"))
    mid = str(last.get("id"))
    created = norm(last.get("created_at"))

    if author != "employer":
        continue

    if seen.get(nid) == mid:
        continue

    low = (vacancy + "\n" + text).lower()

    if any(re.search(p, low, re.I) for p in NO_REPLY_PATTERNS):
        seen[nid] = mid
        ignored += 1
        continue

    if is_past_offline_interview(text):
        seen[nid] = mid
        ignored += 1
        continue

    dedup_key = re.sub(r"\s+", " ", text.lower()).strip()
    if dedup_key in dedup_texts:
        seen[nid] = mid
        ignored += 1
        continue
    dedup_texts.add(dedup_key)

    reason = "review"

    if any(re.search(p, low, re.I) for p in BAD_VACANCY_PATTERNS):
        reason = "bad_or_questionable_vacancy"
    elif any(re.search(p, low, re.I) for p in ASK_HUMAN_PATTERNS):
        reason = "needs_human_decision"
    elif any(re.search(p, low, re.I) for p in AUTO_ANSWER_PATTERNS):
        reason = "possible_ai_answer"

    review.append({
        "negotiation_id": nid,
        "vacancy": vacancy,
        "employer": norm(((n.get("employer") or {}) or {}).get("name")),
        "created_at": created,
        "reason": reason,
        "text": text,
    })

    seen[nid] = mid

SEEN_FILE.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")

if review:
    for item in review:
        append_review(item)
        save_ask_request(item)
    msg = f"Найдено старых диалогов для проверки: {len(review)}\n\n"
    for item in review[:5]:
        msg += f"{item['vacancy']}\n{item['reason']}\n{item['text'][:250]}\n\n"
    ntfy(msg)
    log(f"REVIEW needed={len(review)} ignored={ignored} errors={errors}")
else:
    log(f"OK no new review ignored={ignored} errors={errors}; existing_review={'yes' if REVIEW_FILE.exists() else 'no'}")

print()
print("==== REVIEW FILE ====")
print(REVIEW_FILE)
print()
if review:
    for item in review:
        print("NID:", item["negotiation_id"])
        print("VACANCY:", item["vacancy"])
        print("REASON:", item["reason"])
        print("TEXT:", item["text"][:500])
        print("-" * 80)
else:
    print("none")
