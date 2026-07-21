import csv
import json
import os
import re
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from html import unescape
from pathlib import Path

ROOT = Path("/opt/hh-bot")
STATE = ROOT / "state"
CONFIG = Path("/home/hhbot/.config/hh-applicant-tool/config.json")

MAX_TERMS = int(os.environ.get("SCAN_MAX_TERMS", "45"))
PER_PAGE = int(os.environ.get("SCAN_PER_PAGE", "20"))
MAX_DETAILS = int(os.environ.get("SCAN_MAX_DETAILS", "220"))

EXPS = ["between1And3", "noExperience"]
MODES = ["ekb", "remote"]

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
    return re.sub(r"\s+", " ", s).strip()

def hh_get(path, params=None):
    url = "https://api.hh.ru" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {
        "User-Agent": "hh-bot-scan/1.0",
        "Accept": "application/json",
    }
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))

def parse_filter():
    script = (ROOT / "apply_campaign_safe.sh").read_text(encoding="utf-8", errors="ignore")
    m = re.search(r'EXCLUDED_FILTER="([^"]*)"', script, re.S)
    if not m:
        raise SystemExit("BAD: EXCLUDED_FILTER not found")
    filt = m.group(1)
    return filt, re.compile(filt, re.I | re.S)

def sent_ids_from_logs():
    ids = set()
    paths = list((ROOT / "logs").glob("*.log")) + [Path("/home/hhbot/.config/hh-applicant-tool/log.txt")]
    for p in paths:
        if not p.exists():
            continue
        txt = p.read_text(encoding="utf-8", errors="ignore")
        ids.update(re.findall(r"hh\.ru/vacancy/(\d+)", txt))
        ids.update(re.findall(r"'vacancy_id':\s*'(\d+)'", txt))
        ids.update(re.findall(r'"vacancy_id":\s*"(\d+)"', txt))
    return ids

def load_terms():
    p = ROOT / "apply_targets.txt"
    lines = []
    if p.exists():
        for x in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            x = x.strip()
            if not x or x.startswith("#"):
                continue
            lines.append(x)

    extra = [
        "Python",
        "Программист Python",
        "Python Django",
        "Backend Python",
        "Python API",
        "Python SQL",
        "Python интеграции",
        "Технический специалист Python",
        "Специалист автоматизации Python",
        "Junior Python",
        "Стажер Python",
        "AI Python",
        "боты Python",
    ]

    out = []
    seen = set()
    for x in extra + lines:
        k = x.lower()
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out[:MAX_TERMS]

def snippet_text(item):
    sn = item.get("snippet") or {}
    return clean_html(" ".join(str(sn.get(k) or "") for k in ["requirement", "responsibility"]))

def search_vacancies(terms):
    found = {}
    errors = []

    for term in terms:
        for mode in MODES:
            for exp in EXPS:
                params = {
                    "text": term,
                    "per_page": PER_PAGE,
                    "page": 0,
                    "period": 14,
                    "experience": exp,
                    "order_by": "publication_time",
                }

                if mode == "ekb":
                    params["area"] = "3"
                else:
                    params["area"] = "113"
                    params["schedule"] = "remote"

                try:
                    data = hh_get("/vacancies", params)
                    items = data.get("items") or []
                    for item in items:
                        vid = str(item.get("id") or "")
                        if not vid:
                            continue
                        rec = found.setdefault(vid, {
                            "id": vid,
                            "sources": [],
                            "search_items": [],
                        })
                        rec["sources"].append(f"{term} | {mode} | {exp}")
                        rec["search_items"].append(item)
                except Exception as e:
                    errors.append(f"{term} | {mode} | {exp}: {repr(e)}")
                time.sleep(0.15)

    return found, errors

def fetch_details(found):
    rows = []
    ids = list(found.keys())[:MAX_DETAILS]

    for i, vid in enumerate(ids, 1):
        item = found[vid]["search_items"][0]
        detail = {}
        desc = ""
        try:
            detail = hh_get(f"/vacancies/{vid}")
            desc = clean_html(detail.get("description"))
        except Exception as e:
            detail = {}
            desc = "DETAIL_ERROR: " + repr(e)

        name = detail.get("name") or item.get("name") or ""
        employer = ((detail.get("employer") or item.get("employer") or {}) or {}).get("name") or ""
        area = ((detail.get("area") or item.get("area") or {}) or {}).get("name") or ""
        schedule = ((detail.get("schedule") or item.get("schedule") or {}) or {}).get("name") or ""
        employment = ((detail.get("employment") or item.get("employment") or {}) or {}).get("name") or ""
        experience = ((detail.get("experience") or item.get("experience") or {}) or {}).get("name") or ""
        salary = detail.get("salary") or item.get("salary")
        url = detail.get("alternate_url") or item.get("alternate_url") or f"https://hh.ru/vacancy/{vid}"
        snippet = snippet_text(item)

        combined = "\n".join([name, employer, area, schedule, employment, experience, snippet, desc])

        matches = []
        for mm in EX_RX.finditer(combined):
            word = mm.group(0)
            frag = combined[max(0, mm.start() - 80):mm.end() + 140]
            matches.append((word, frag))

        low = combined.lower()

        suspicious = []
        for word in [
            "техническая поддержка",
            "поддержка продукта",
            "консультации клиентов",
            "клиентов",
            "портал поддержки",
            "оборудование",
            "настройка по",
            "1 линия",
            "первая линия",
            "продажи",
            "php",
            "битрикс",
            "1с",
            "devops",
            "qa",
            "тестирование",
            "data scientist",
            "аналитик",
            "ремонт",
            "сборка",
            "диагностика",
        ]:
            if word in low:
                suspicious.append(word)

        if vid in SENT_IDS:
            status = "ALREADY_SENT_OR_SEEN_IN_LOGS"
        elif matches:
            status = "BLOCKED_BY_FILTER"
        elif suspicious:
            status = "NOT_BLOCKED_BUT_SUSPICIOUS"
        else:
            status = "GOOD_NOT_BLOCKED"

        rows.append({
            "id": vid,
            "name": name,
            "employer": employer,
            "area": area,
            "schedule": schedule,
            "employment": employment,
            "experience": experience,
            "salary": salary,
            "url": url,
            "sources": found[vid]["sources"][:8],
            "status": status,
            "matches": matches,
            "suspicious": suspicious,
            "snippet": snippet,
            "description": desc[:1200],
        })

        time.sleep(0.12)

    return rows

def salary_str(s):
    if not s:
        return ""
    if isinstance(s, dict):
        return f"{s.get('from')}..{s.get('to')} {s.get('currency')}"
    return str(s)

def print_row(row, show_desc=False):
    print("-" * 100)
    print(f"{row['status']} | {row['id']}")
    print("Название:", row["name"])
    print("Компания:", row["employer"])
    print("Город:", row["area"])
    print("График:", row["schedule"])
    print("Опыт:", row["experience"])
    print("ЗП:", salary_str(row["salary"]))
    print("URL:", row["url"])
    print("Нашлось по:", "; ".join(row["sources"][:4]))
    if row["matches"]:
        print("РЕЖЕТ ФИЛЬТР:")
        for word, frag in row["matches"][:6]:
            print("  MATCH:", repr(word))
            print("  TEXT:", frag[:260])
    if row["suspicious"]:
        print("ПОДОЗРИТЕЛЬНО:", ", ".join(row["suspicious"][:10]))
    if show_desc:
        print("Описание:", row["description"][:700])

TOKEN = None
if CONFIG.exists():
    TOKEN = find_token(json.loads(CONFIG.read_text(encoding="utf-8")))

print("TOKEN FOUND:", bool(TOKEN))

EX_FILTER, EX_RX = parse_filter()
SENT_IDS = sent_ids_from_logs()
TERMS = load_terms()

print("TERMS:", len(TERMS))
print("SENT/SEEN IDS IN LOGS:", len(SENT_IDS))
print("=" * 100)

found, errors = search_vacancies(TERMS)
print("FOUND UNIQUE VACANCIES:", len(found))
print("SEARCH ERRORS:", len(errors))
for e in errors[:20]:
    print("ERROR:", e)

print("=" * 100)
rows = fetch_details(found)

cnt = Counter(r["status"] for r in rows)
print("SUMMARY:")
for k, v in cnt.most_common():
    print(k + ":", v)

match_counter = Counter()
for r in rows:
    for word, frag in r["matches"]:
        match_counter[word.lower()] += 1

print()
print("TOP FILTER MATCHES:")
for word, n in match_counter.most_common(30):
    print(f"{word}: {n}")

print()
print("=" * 100)
print("GOOD_NOT_BLOCKED, возможно боту стоит брать:")
for r in [x for x in rows if x["status"] == "GOOD_NOT_BLOCKED"][:35]:
    print_row(r)

print()
print("=" * 100)
print("BLOCKED_BY_FILTER, почему бот не взял:")
for r in [x for x in rows if x["status"] == "BLOCKED_BY_FILTER"][:45]:
    print_row(r)

print()
print("=" * 100)
print("NOT_BLOCKED_BUT_SUSPICIOUS, мусор который может пролезть:")
for r in [x for x in rows if x["status"] == "NOT_BLOCKED_BUT_SUSPICIOUS"][:45]:
    print_row(r)

print()
print("=" * 100)
print("ALREADY_SENT_OR_SEEN_IN_LOGS:")
for r in [x for x in rows if x["status"] == "ALREADY_SENT_OR_SEEN_IN_LOGS"][:30]:
    print_row(r)

# CSV report
csv_path = STATE / f"vacancy-scan-{time.strftime('%F-%H%M%S')}.csv"
latest_path = STATE / "vacancy-scan-latest.csv"

with csv_path.open("w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=[
        "status", "id", "name", "employer", "area", "schedule",
        "experience", "salary", "url", "matches", "suspicious", "sources",
    ])
    w.writeheader()
    for r in rows:
        w.writerow({
            "status": r["status"],
            "id": r["id"],
            "name": r["name"],
            "employer": r["employer"],
            "area": r["area"],
            "schedule": r["schedule"],
            "experience": r["experience"],
            "salary": salary_str(r["salary"]),
            "url": r["url"],
            "matches": "; ".join(w for w, _ in r["matches"]),
            "suspicious": "; ".join(r["suspicious"]),
            "sources": "; ".join(r["sources"]),
        })

latest_path.write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")

print()
print("CSV REPORT:", csv_path)
print("CSV LATEST:", latest_path)
