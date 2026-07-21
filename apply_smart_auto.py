import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path("/opt/hh-bot")
RESUME_ID = "a89be050ff10a4a4fc0039ed1f786946636470"

MAX_DAILY = int(os.environ.get("APPLY_MAX_DAILY", "35"))
BATCH_SIZE = int(os.environ.get("APPLY_BATCH_SIZE", "2"))

TODAY = time.strftime("%F", time.gmtime())
COUNT_FILE = ROOT / "state" / f"apply-count-{TODAY}.txt"
COUNT_FILE.parent.mkdir(parents=True, exist_ok=True)

def read_count():
    try:
        return int(COUNT_FILE.read_text().strip() or "0")
    except Exception:
        return 0

def write_count(n):
    COUNT_FILE.write_text(str(int(n)), encoding="utf-8")

def sent_count(text):
    nums = [int(x) for x in re.findall(r"Отправлено:\s*(\d+)", text)]
    if nums and sum(nums) > 0:
        return sum(nums)
    return len(re.findall(r"Отправили отклик на вакансию", text))

def read_filter():
    for name in ["apply_campaign_safe_core.sh", "apply_campaign_safe.sh"]:
        p = ROOT / name
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r'EXCLUDED_FILTER="([^"]*)"', text, re.S)
        if m:
            return m.group(1)
    return ""

SYSTEM_PROMPT = (ROOT / "cover_letter_system_prompt.txt").read_text(encoding="utf-8")
MESSAGE_PROMPT = (ROOT / "cover_letter_message_prompt.txt").read_text(encoding="utf-8")
EXCLUDED_FILTER = read_filter()
EXTRA_EXCLUDED = (
    r"преподавател|репетитор|обучение детей|работа с детьми|дети|детский|школьник|школа|курс|курсы|ментор|наставник|teacher|tutor|kids|children|"
    r"data scientist|data science|machine learning|bi analyst|"
    r"робототехник|arduino|stm32|embedded|revit|autocad|bim|амбассадор|промо|промо-акц|флаер|раздача|мастер.?класс|привлечени[ея] клиентов|привлекать детей|школ[аы]|дет[еи]й|лего|lego"
)
if EXCLUDED_FILTER:
    EXCLUDED_FILTER = EXCLUDED_FILTER + "|" + EXTRA_EXCLUDED
else:
    EXCLUDED_FILTER = EXTRA_EXCLUDED

# Порядок важен: сначала самые подходящие, потом шире.
TRIES = [
    # Самое целевое: Python/backend/API/автоматизация
    ("remote", "between1And3", "Django"),
    ("remote", "between1And3", "FastAPI"),
    ("remote", "between1And3", "Flask"),
    ("remote", "between1And3", "Python SQL"),
    ("remote", "between1And3", "SQL Python"),
    ("remote", "between1And3", "Python automation"),
    ("remote", "between1And3", "автоматизация Python"),
    ("remote", "between1And3", "разработчик ботов Python"),
    ("remote", "between1And3", "бот Python"),
    ("remote", "between1And3", "интеграции API"),
    ("remote", "noExperience", "Python"),
    ("remote", "noExperience", "Django"),
    ("remote", "noExperience", "FastAPI"),
    ("ekb", "between1And3", "Django"),
    ("ekb", "between1And3", "FastAPI"),
    ("ekb", "between1And3", "Программист Python"),
    ("ekb", "between1And3", "Python разработчик"),
    ("ekb", "between1And3", "Python API SQL"),
    ("ekb", "between1And3", "Python интеграции"),
    ("ekb", "between1And3", "Backend Python"),
    ("ekb", "noExperience", "Стажер Python"),
    ("ekb", "noExperience", "Junior Python"),

    ("remote", "between1And3", "Python developer"),
    ("remote", "between1And3", "Python backend"),
    ("remote", "between1And3", "Python API"),
    ("remote", "between1And3", "Python integration"),
    ("remote", "between1And3", "Django developer"),

    ("remote", "noExperience", "Junior Python Developer"),
    ("remote", "noExperience", "Python стажер"),
    ("remote", "noExperience", "Python automation"),

    # Frontend / React / Fullstack
    ("remote", "noExperience", "Frontend React junior"),
    ("remote", "noExperience", "JavaScript developer junior"),
    ("remote", "noExperience", "React developer junior"),
    ("remote", "between1And3", "Frontend React"),
    ("remote", "between1And3", "JavaScript developer"),
    ("remote", "between1And3", "Fullstack developer"),
    ("remote", "between1And3", "Python React"),
    ("remote", "between1And3", "Django React"),

    ("ekb", "noExperience", "Frontend React junior"),
    ("ekb", "noExperience", "JavaScript junior"),
    ("ekb", "between1And3", "Frontend React"),
    ("ekb", "between1And3", "Fullstack developer"),

    # CRM / интеграции / технический специалист
    ("remote", "noExperience", "CRM интегратор"),
    ("remote", "between1And3", "CRM интегратор"),
    ("remote", "between1And3", "Bitrix24 интегратор"),
    ("remote", "between1And3", "amoCRM интегратор"),
    ("remote", "between1And3", "интеграции CRM"),
    ("remote", "between1And3", "технический специалист IT"),
    ("remote", "between1And3", "специалист по автоматизации"),
    ("remote", "between1And3", "API интеграции"),

    ("ekb", "noExperience", "CRM интегратор"),
    ("ekb", "between1And3", "технический специалист IT"),
    ("ekb", "between1And3", "специалист по автоматизации"),
    ("ekb", "between1And3", "интеграции CRM"),

    # AI / low-code / no-code / вайбкодинг
    ("remote", "noExperience", "AI automation"),
    ("remote", "between1And3", "AI automation"),
    ("remote", "between1And3", "LLM automation"),
    ("remote", "between1And3", "low-code developer"),
    ("remote", "between1And3", "no-code automation"),
    ("remote", "between1And3", "вайбкодер"),
    ("remote", "between1And3", "ИИ автоматизация"),

    ("ekb", "between1And3", "AI automation"),
    ("ekb", "between1And3", "ИИ автоматизация"),
    ("ekb", "between1And3", "вайбкодер"),

    # Junior DevOps / Linux / Bash / scripts
    ("remote", "noExperience", "Junior DevOps Linux"),
    ("remote", "between1And3", "Junior DevOps Python"),
    ("remote", "between1And3", "Linux Bash Python"),
    ("remote", "between1And3", "Python Bash автоматизация"),

    ("ekb", "noExperience", "Junior DevOps Linux"),
    ("ekb", "between1And3", "Linux Bash Python"),

    # SQL / аналитика / системный аналитик
    ("remote", "noExperience", "SQL analyst junior"),
    ("remote", "between1And3", "аналитик данных SQL"),
    ("remote", "between1And3", "системный аналитик junior"),
    ("remote", "between1And3", "технический аналитик"),
    ("remote", "between1And3", "SQL аналитик"),

    ("ekb", "noExperience", "SQL analyst junior"),
    ("ekb", "between1And3", "аналитик данных SQL"),
    ("ekb", "between1And3", "системный аналитик junior"),
    ("ekb", "between1And3", "технический аналитик"),

    # Java/C#/PHP только если junior/trainee/обучение
    ("remote", "noExperience", "Java junior обучение"),
    ("remote", "noExperience", "C# junior обучение"),
    ("remote", "noExperience", "PHP junior обучение"),
    ("ekb", "noExperience", "Java junior обучение"),
    ("ekb", "noExperience", "C# junior обучение"),
    ("ekb", "noExperience", "PHP junior обучение"),

    # Админ сайта / контент + техчасть — только удалёнка
    ("remote", "between1And3", "администратор сайта удаленно"),
    ("remote", "between1And3", "контент менеджер сайт удаленно"),
    ("remote", "between1And3", "технический администратор сайта"),
]

before = read_count()
left_today = max(0, MAX_DAILY - before)
target = min(BATCH_SIZE, left_today)

print(f"===== smart apply start | count={before}/{MAX_DAILY} | target={target} =====")

if target <= 0:
    print("DAILY LIMIT REACHED")
    raise SystemExit(0)

total_sent = 0

for mode, exp, search in TRIES:
    if total_sent >= target:
        break

    print("=" * 100)
    print(f"TRY: mode={mode} exp={exp} search={search}")

    cmd = [
        "/opt/hh-bot/venv/bin/hh-applicant-tool",
        "apply-vacancies",
        "--resume-id", RESUME_ID,
        "--search", search,
        "--experience", exp,
        "--salary", "30000",
        "--period", "30",
        "--per-page", str(max(1, target - total_sent)),
        "--total-pages", "1",
        "--use-ai",
        "--ai-filter", "light",
        "--system-prompt", SYSTEM_PROMPT,
        "--message-prompt", MESSAGE_PROMPT,
        "--force-message",
        "--no-send-email",
        "--excluded-filter", EXCLUDED_FILTER,
    ]

    if mode == "ekb":
        cmd += ["--area", "3"]
    else:
        cmd += ["--schedule", "remote"]

    try:
        r = subprocess.run(
            cmd,
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=180,
        )
        out = r.stdout or ""
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + "\nTIMEOUT\n"
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="ignore")
        r = None

    print(out)

    n = sent_count(out)
    total_sent += n

    print(f"TRY SENT: {n}")
    print(f"TOTAL SENT SO FAR: {total_sent}")

    # маленькая пауза, чтобы не долбить HH
    time.sleep(2)

after = before + total_sent
write_count(after)

print("=" * 100)
print(f"===== smart apply end | before={before} | actual_sent={total_sent} | after={after} =====")
