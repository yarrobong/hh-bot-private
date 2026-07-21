import json
import re
import urllib.request
from html import unescape
from pathlib import Path

VID = "134945058"
ROOT = Path("/opt/hh-bot")

print("VACANCY ID:", VID)
print("=" * 100)

# 1. Проверяем, была ли вакансия уже в логах
print("---- LOG CHECK ----")
found = False
for p in list((ROOT / "logs").glob("*.log")) + [Path("/home/hhbot/.config/hh-applicant-tool/log.txt")]:
    if not p.exists():
        continue
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    if VID in text:
        found = True
        print("FOUND IN:", p)
        for line in text.splitlines():
            if VID in line:
                print(line[-1000:])
print("already in logs:", found)
print()

# 2. Грузим вакансию через HH API
print("---- HH API ----")
url = f"https://api.hh.ru/vacancies/{VID}"
req = urllib.request.Request(url, headers={"User-Agent": "hh-bot-debug/1.0"})
with urllib.request.urlopen(req, timeout=20) as r:
    data = json.loads(r.read().decode("utf-8"))

def clean_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

name = data.get("name")
employer = (data.get("employer") or {}).get("name")
area = (data.get("area") or {}).get("name")
schedule = (data.get("schedule") or {}).get("name")
employment = (data.get("employment") or {}).get("name")
experience = (data.get("experience") or {}).get("name")
salary = data.get("salary")
alternate_url = data.get("alternate_url")
description = clean_html(data.get("description"))

print("Название:", name)
print("Компания:", employer)
print("Город:", area)
print("График:", schedule)
print("Занятость:", employment)
print("Опыт:", experience)
print("ЗП:", salary)
print("URL:", alternate_url)
print()

# 3. Проверяем стоп-фильтр из apply_campaign_safe.sh
print("---- EXCLUDED FILTER CHECK ----")
script = (ROOT / "apply_campaign_safe.sh").read_text(encoding="utf-8", errors="ignore")
m = re.search(r'EXCLUDED_FILTER="([^"]*)"', script, re.S)
excluded = m.group(1) if m else ""

combined = "\n".join([
    str(name or ""),
    str(employer or ""),
    str(area or ""),
    str(schedule or ""),
    str(employment or ""),
    str(experience or ""),
    description,
])

if not excluded:
    print("BAD: EXCLUDED_FILTER not found")
else:
    print("filter length:", len(excluded))
    try:
        rx = re.compile(excluded, re.I | re.S)
        matches = []
        for mm in rx.finditer(combined):
            frag = combined[max(0, mm.start()-80):mm.end()+120]
            matches.append((mm.group(0), frag))
        if matches:
            print("BLOCKED BY FILTER: YES")
            for i, (word, frag) in enumerate(matches[:30], 1):
                print("-" * 80)
                print(f"{i}. MATCH:", repr(word))
                print("TEXT:", frag)
        else:
            print("BLOCKED BY FILTER: NO")
    except Exception as e:
        print("BAD REGEX:", e)

print()

# 4. Быстрая оценка условий
print("---- SIMPLE FIT CHECK ----")
text_low = combined.lower()

bad_flags = []

if area and area.lower() not in ["екатеринбург", "россия"]:
    if schedule and "удален" not in schedule.lower() and "удал" not in text_low:
        bad_flags.append("город не Екатеринбург и не видно удалёнки")

if salary:
    frm = salary.get("from")
    to = salary.get("to")
    cur = salary.get("currency")
    if cur == "RUR":
        if to is not None and to < 45000:
            bad_flags.append("верхняя зарплата ниже 45к")
else:
    print("ЗП не указана — это не всегда блок, но бот мог хуже ранжировать")

if experience and "более 6" in experience.lower():
    bad_flags.append("опыт слишком высокий")
if experience and "3–6" in experience.lower():
    bad_flags.append("опыт 3-6 лет, может быть выше текущего профиля")

if bad_flags:
    print("POSSIBLE PROBLEMS:")
    for x in bad_flags:
        print("-", x)
else:
    print("по простым условиям выглядит не заблокированной")

print()

# 5. Кусок описания
print("---- DESCRIPTION PREVIEW ----")
print(description[:1800])
