import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HH = "https://api.hh.ru/vacancies"

QUERIES = [
    # УДАЛЁНКА ПО РОССИИ — основные Python/backend
    ("remote", "between1And3", "Python"),
    ("remote", "between1And3", "Python разработчик"),
    ("remote", "between1And3", "Python developer"),
    ("remote", "between1And3", "Backend Python"),
    ("remote", "between1And3", "Backend developer"),
    ("remote", "between1And3", "Django"),
    ("remote", "between1And3", "Django developer"),
    ("remote", "between1And3", "FastAPI"),
    ("remote", "between1And3", "Flask"),
    ("remote", "between1And3", "Python API"),
    ("remote", "between1And3", "Python SQL"),
    ("remote", "between1And3", "SQL Python"),
    ("remote", "between1And3", "Python интеграции"),
    ("remote", "between1And3", "интеграции API"),
    ("remote", "between1And3", "автоматизация Python"),
    ("remote", "between1And3", "Python automation"),
    ("remote", "between1And3", "бот Python"),
    ("remote", "between1And3", "разработчик ботов Python"),

    # УДАЛЁНКА ПО РОССИИ — junior/no experience
    ("remote", "noExperience", "Python"),
    ("remote", "noExperience", "Python разработчик"),
    ("remote", "noExperience", "Junior Python"),
    ("remote", "noExperience", "Junior Python Developer"),
    ("remote", "noExperience", "Python junior"),
    ("remote", "noExperience", "Python стажер"),
    ("remote", "noExperience", "Стажер Python"),
    ("remote", "noExperience", "Django"),
    ("remote", "noExperience", "FastAPI"),
    ("remote", "noExperience", "Python API"),
    ("remote", "noExperience", "Python automation"),
    ("remote", "noExperience", "автоматизация Python"),

    # ЕКАТЕРИНБУРГ — офис/гибрид можно
    ("ekb", "between1And3", "Python"),
    ("ekb", "between1And3", "Python разработчик"),
    ("ekb", "between1And3", "Программист Python"),
    ("ekb", "between1And3", "Backend Python"),
    ("ekb", "between1And3", "Django"),
    ("ekb", "between1And3", "FastAPI"),
    ("ekb", "between1And3", "Python API"),
    ("ekb", "between1And3", "Python SQL"),
    ("ekb", "between1And3", "Python интеграции"),
    ("ekb", "between1And3", "автоматизация Python"),
    ("ekb", "noExperience", "Python"),
    ("ekb", "noExperience", "Junior Python"),
    ("ekb", "noExperience", "Стажер Python"),
    ("ekb", "noExperience", "Python стажер"),
]

BAD_WORDS = [
    "php", "laravel", "symfony",
    "java разработчик", "java developer", "c++", "c#", ".net",
    "react", "frontend", "фронтенд",
    "1с", "битрикс разработчик",
    "qa", "тестировщик", "тестирование",
    "devops", "kubernetes", "k8s", "ci/cd",
    "data engineer", "dwh", "bi разработчик", "аналитик",
    "ml engineer", "data scientist",
    "иб", "пентест", "pentest", "reverse",
    "преподаватель", "репетитор",
    "продажи", "менеджер проекта", "project manager",
]

GOOD_HINTS = [
    "python", "django", "fastapi", "flask", "sql", "api",
    "backend", "бекенд", "бэкенд",
    "интеграц", "автоматизац", "бот",
    "техническ", "support", "поддержк",
]

def params_for(mode, exp, text, page):
    params = {
        "text": text,
        "experience": exp,
        "per_page": 100,
        "page": page,
        "order_by": "publication_time",
        "only_with_salary": "false",
    }

    if mode == "ekb":
        # Екатеринбург
        params["area"] = "3"
    elif mode == "remote":
        # Россия + удалёнка
        params["area"] = "113"
        params["schedule"] = "remote"
    else:
        params["area"] = "113"

    return params

def fetch(mode, exp, text, page):
    params = params_for(mode, exp, text, page)
    url = HH + "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 hh-bot-market-audit",
            "HH-User-Agent": "hh-bot-market-audit",
        },
    )

    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))

def text_of(v):
    chunks = [
        v.get("name") or "",
        (v.get("employer") or {}).get("name") or "",
        (v.get("snippet") or {}).get("requirement") or "",
        (v.get("snippet") or {}).get("responsibility") or "",
    ]
    return " ".join(chunks).lower()

def is_probably_relevant(v):
    t = text_of(v)

    if any(bad in t for bad in BAD_WORDS):
        return False

    if any(good in t for good in GOOD_HINTS):
        return True

    return False

print("VACANCY POOL AUDIT", datetime.now(timezone.utc).isoformat())
print("=" * 120)

unique_all = {}
unique_relevant = {}

rows = []

for mode, exp, text in QUERIES:
    found = -1
    pages = 0
    scanned = 0
    relevant = 0
    error = ""

    try:
        first = fetch(mode, exp, text, 0)
        found = int(first.get("found", 0))
        pages = int(first.get("pages", 0))

        # HH обычно не даёт бесконечно листать, поэтому берём до 20 страниц максимум.
        max_pages = min(pages, 20)

        for page in range(max_pages):
            data = first if page == 0 else fetch(mode, exp, text, page)
            items = data.get("items", [])
            scanned += len(items)

            for v in items:
                vid = str(v.get("id"))
                if not vid:
                    continue

                name = v.get("name") or ""
                url = v.get("alternate_url") or f"https://hh.ru/vacancy/{vid}"
                employer = (v.get("employer") or {}).get("name") or ""
                area = (v.get("area") or {}).get("name") or ""
                schedule = (v.get("schedule") or {}).get("name") or ""
                salary = v.get("salary")
                salary_txt = ""
                if salary:
                    salary_txt = f"{salary.get('from') or ''}-{salary.get('to') or ''} {salary.get('currency') or ''}".strip()

                unique_all[vid] = (name, employer, area, schedule, salary_txt, url)

                if is_probably_relevant(v):
                    relevant += 1
                    unique_relevant[vid] = (name, employer, area, schedule, salary_txt, url)

            time.sleep(0.25)

    except Exception as e:
        error = str(e)

    rows.append((found, pages, scanned, relevant, mode, exp, text, error))

rows.sort(reverse=True, key=lambda x: (x[3], x[0]))

print("BY QUERY")
print("-" * 120)
for found, pages, scanned, relevant, mode, exp, text, error in rows:
    if error:
        print(f"ERROR | mode={mode:<6} exp={exp:<12} | {text} | {error}")
    else:
        print(f"{relevant:5} relevant | {scanned:5} scanned | {found:6} found | pages={pages:<3} | mode={mode:<6} exp={exp:<12} | {text}")

print("=" * 120)
print(f"UNIQUE ALL SCANNED: {len(unique_all)}")
print(f"UNIQUE PROBABLY RELEVANT AFTER LIGHT FILTER: {len(unique_relevant)}")
print("=" * 120)

print("TOP RELEVANT EXAMPLES")
print("-" * 120)
for i, (vid, row) in enumerate(list(unique_relevant.items())[:80], 1):
    name, employer, area, schedule, salary_txt, url = row
    print(f"{i:02}. {name} | {employer} | {area} | {schedule} | {salary_txt} | {url}")

print("=" * 120)
print("DONE")
