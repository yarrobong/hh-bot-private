import json
import os
import re
import urllib.request
from html import unescape
from pathlib import Path

VID = "134945058"
ROOT = Path("/opt/hh-bot")
CONFIG = Path("/home/hhbot/.config/hh-applicant-tool/config.json")

def find_token(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in {"access_token", "access"} and isinstance(v, str) and len(v) > 20:
                return v
            found = find_token(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = find_token(v)
            if found:
                return found
    return None

def clean_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

print("VACANCY ID:", VID)
print("=" * 100)

print("---- LOG CHECK ----")
found = False
for p in list((ROOT / "logs").glob("*.log")) + [Path("/home/hhbot/.config/hh-applicant-tool/log.txt")]:
    if not p.exists():
        continue
    text = p.read_text(encoding="utf-8", errors="ignore")
    if VID in text:
        found = True
        print("FOUND IN:", p)
        for line in text.splitlines():
            if VID in line:
                print(line[-1000:])
print("already in logs:", found)
print()

token = None
if CONFIG.exists():
    try:
        token = find_token(json.loads(CONFIG.read_text(encoding="utf-8")))
    except Exception as e:
        print("config read error:", e)

print("---- TOKEN CHECK ----")
print("token found:", bool(token))
print()

print("---- HH API AUTH ----")
headers = {
    "User-Agent": "hh-bot-debug/1.0",
    "Accept": "application/json",
}
if token:
    headers["Authorization"] = "Bearer " + token

url = f"https://api.hh.ru/vacancies/{VID}"
req = urllib.request.Request(url, headers=headers)

try:
    with urllib.request.urlopen(req, timeout=25) as r:
        data = json.loads(r.read().decode("utf-8"))
except Exception as e:
    print("API ERROR:", repr(e))
    raise SystemExit(1)

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
            frag = combined[max(0, mm.start()-100):mm.end()+160]
            matches.append((mm.group(0), frag))
        if matches:
            print("BLOCKED BY FILTER: YES")
            for i, (word, frag) in enumerate(matches[:40], 1):
                print("-" * 80)
                print(f"{i}. MATCH:", repr(word))
                print("TEXT:", frag)
        else:
            print("BLOCKED BY FILTER: NO")
    except Exception as e:
        print("BAD REGEX:", e)

print()
print("---- SIMPLE FIT CHECK ----")
bad = []

low = combined.lower()

if salary:
    frm = salary.get("from")
    to = salary.get("to")
    cur = salary.get("currency")
    print("salary from/to/currency:", frm, to, cur)
    if cur == "RUR" and to is not None and to < 45000:
        bad.append("верхняя зарплата ниже 45к")
else:
    print("salary: не указана")

if experience and ("3–6" in experience or "3-6" in experience or "более 6" in experience.lower()):
    bad.append("опыт может быть выше профиля")

if area and area.lower() != "екатеринбург":
    if not schedule or "удален" not in schedule.lower():
        if "удален" not in low and "удалён" not in low:
            bad.append("не Екатеринбург и не видно удалёнки")

if bad:
    print("POSSIBLE PROBLEMS:")
    for x in bad:
        print("-", x)
else:
    print("по простым условиям выглядит подходящей")

print()
print("---- DESCRIPTION PREVIEW ----")
print(description[:2200])
