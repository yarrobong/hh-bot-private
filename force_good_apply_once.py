import re
import subprocess
from pathlib import Path

ROOT = Path("/opt/hh-bot")
RESUME_ID = "a89be050ff10a4a4fc0039ed1f786946636470"

SYSTEM_PROMPT = (ROOT / "cover_letter_system_prompt.txt").read_text(encoding="utf-8")
MESSAGE_PROMPT = (ROOT / "cover_letter_message_prompt.txt").read_text(encoding="utf-8")

script = (ROOT / "apply_campaign_safe_core.sh").read_text(encoding="utf-8", errors="ignore")
m = re.search(r'EXCLUDED_FILTER="([^"]*)"', script, re.S)
EXCLUDED_FILTER = m.group(1) if m else ""

tries = [
    # Сначала точечно пытаемся найти ту самую СДЭК/Екатеринбург
    ("ekb", "between1And3", "СДЭК Python"),
    ("ekb", "between1And3", "Программист Python"),
    ("ekb", "between1And3", "Python API SQL"),
    ("ekb", "between1And3", "Python интеграции"),

    # Потом нормальная удалёнка
    ("remote", "between1And3", "Python developer"),
    ("remote", "between1And3", "Python backend"),
    ("remote", "between1And3", "Python API"),
    ("remote", "noExperience", "Junior Python Developer"),
]

def sent_count(text):
    nums = [int(x) for x in re.findall(r"Отправлено:\s*(\d+)", text)]
    if nums and sum(nums) > 0:
        return sum(nums)
    return len(re.findall(r"Отправили отклик на вакансию", text))

total_sent = 0

for mode, exp, search in tries:
    print("=" * 100)
    print(f"TRY: mode={mode} exp={exp} search={search}")

    cmd = [
        "/opt/hh-bot/venv/bin/hh-applicant-tool",
        "apply-vacancies",
        "--resume-id", RESUME_ID,
        "--search", search,
        "--experience", exp,
        "--salary", "45000",
        "--period", "30",
        "--per-page", "5",
        "--total-pages", "1",
        "--use-ai",
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

    r = subprocess.run(
        cmd,
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
    )

    out = r.stdout or ""
    print(out)

    n = sent_count(out)
    total_sent += n

    print(f"TRY SENT: {n}")

    # Останавливаемся после первого успешного реального отклика, чтобы не разнести всё пачкой
    if total_sent > 0:
        break

print("=" * 100)
print("TOTAL_SENT:", total_sent)
