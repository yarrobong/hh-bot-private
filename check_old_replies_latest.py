import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

BASE = Path("/opt/hh-bot")
STATE = BASE / "state" / "backfill_seen.json"
STATE.parent.mkdir(parents=True, exist_ok=True)

if STATE.exists():
    seen = json.loads(STATE.read_text(encoding="utf-8"))
else:
    seen = {}

def call_api(args):
    res = subprocess.run(
        ["/opt/hh-bot/venv/bin/hh-applicant-tool", "call-api", *args],
        text=True,
        capture_output=True,
    )
    if res.returncode != 0:
        return None
    raw = res.stdout.strip()
    if not raw.startswith("{"):
        return None
    return json.loads(raw)

def norm(s):
    return (s or "").replace("\xa0", " ").strip()

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
    r"frontend",
    r"react",
    r"java\b",
    r"vb\.net",
    r"asp\.net",
    r"c\+\+",
    r"qt",
    r"devops",
    r"dwh",
    r"аналитик",
    r"bim",
    r"рабочий",
    r"разнорабочий",
    r"слесарь",
    r"кормовые",
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
    print("ERROR: cannot load negotiations")
    raise SystemExit(1)

need_human = []
auto_possible = []
ignored = []
errors = []

for n in data.get("items", []):
    nid = str(n.get("id"))
    vacancy = norm((n.get("vacancy") or {}).get("name"))
    updated = norm(n.get("updated_at"))
    state = (n.get("state") or {}).get("id")

    if state != "response":
        continue

    msg_data = call_api([f"/negotiations/{nid}/messages", "page=0", "per_page=20"])
    if not msg_data:
        errors.append((nid, vacancy, "messages forbidden/error"))
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
        ignored.append((nid, vacancy, created, "no_reply", text[:180]))
        seen[nid] = mid
        continue

    if any(re.search(p, low, re.I) for p in BAD_VACANCY_PATTERNS):
        need_human.append((nid, vacancy, created, "bad_or_questionable_vacancy", text))
        continue

    if any(re.search(p, low, re.I) for p in ASK_HUMAN_PATTERNS):
        need_human.append((nid, vacancy, created, "needs_human_decision", text))
        continue

    if any(re.search(p, low, re.I) for p in AUTO_ANSWER_PATTERNS):
        auto_possible.append((nid, vacancy, created, "auto_possible", text))
        continue

    need_human.append((nid, vacancy, created, "unknown_needs_review", text))

STATE.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")

print()
print("==== NEED HUMAN / REVIEW ====")
if not need_human:
    print("none")
else:
    for nid, vacancy, created, reason, text in need_human:
        print()
        print("NID:", nid)
        print("VACANCY:", vacancy)
        print("CREATED:", created)
        print("REASON:", reason)
        print("TEXT:")
        print(text[:1200])
        print("-" * 90)

print()
print("==== AUTO POSSIBLE ====")
if not auto_possible:
    print("none")
else:
    for nid, vacancy, created, reason, text in auto_possible:
        print()
        print("NID:", nid)
        print("VACANCY:", vacancy)
        print("CREATED:", created)
        print("REASON:", reason)
        print("TEXT:")
        print(text[:1200])
        print("-" * 90)

print()
print("==== IGNORED NO-REPLY ====")
print("count:", len(ignored))
for row in ignored[:20]:
    print(row[0], "|", row[1], "|", row[3], "|", row[4])

print()
print("==== ERRORS / FORBIDDEN ====")
print("count:", len(errors))
for row in errors[:30]:
    print(row[0], "|", row[1], "|", row[2])
