from pathlib import Path
import subprocess
import re

ROOT = Path("/opt/hh-bot")
LOG = Path("/home/hhbot/.config/hh-applicant-tool/log.txt")
TODAY = subprocess.check_output(["date", "-u", "+%F"], text=True).strip()
COUNT_FILE = ROOT / "state" / f"apply-count-{TODAY}.txt"

script = (ROOT / "apply_campaign_safe.sh").read_text(encoding="utf-8", errors="ignore")
m = re.search(r'EXCLUDED_FILTER="([^"]*)"', script)
excluded = m.group(1) if m else ""

system_prompt = (ROOT / "cover_letter_system_prompt.txt").read_text(encoding="utf-8", errors="ignore")
message_prompt = (ROOT / "cover_letter_message_prompt.txt").read_text(encoding="utf-8", errors="ignore")

try:
    old_count = int(COUNT_FILE.read_text(encoding="utf-8").strip() or "4")
except Exception:
    old_count = 4

searches = [
    ("remote", "between1And3", "Python разработчик"),
    ("remote", "between1And3", "Python Django"),
    ("remote", "between1And3", "Backend Python"),
    ("remote", "between1And3", "Python API"),
    ("remote", "between1And3", "Python интеграции"),
    ("remote", "between1And3", "разработчик чат-ботов Python"),
    ("remote", "between1And3", "AI Python Engineer"),
    ("remote", "between1And3", "Vibe coding Python"),
]

LOG.write_text("", encoding="utf-8")

sent = False

for i, (_mode, exp, search) in enumerate(searches, 1):
    print()
    print("=" * 90)
    print(f"TRY {i}: {search}")
    print("=" * 90)

    cmd = [
        "/opt/hh-bot/venv/bin/hh-applicant-tool",
        "apply-vacancies",
        "--resume-id", "a89be050ff10a4a4fc0039ed1f786946636470",
        "--search", search,
        "--schedule", "remote",
        "--experience", exp,
        "--salary", "45000",
        "--period", "30",
        "--per-page", "1",
        "--total-pages", "1",
        "--use-ai",
        "--system-prompt", system_prompt,
        "--message-prompt", message_prompt,
        "--force-message",
        "--no-send-email",
        "--excluded-filter", excluded,
    ]

    try:
        r = subprocess.run(
            cmd,
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
        out = r.stdout or ""
        print(out)
    except subprocess.TimeoutExpired:
        print("[TIMEOUT]")
        continue
    except Exception as e:
        print("[ERROR]", repr(e))
        continue

    if "Отправили отклик" in out or "Отправлено: 1" in out:
        sent = True
        COUNT_FILE.write_text(str(old_count + 1) + "\n", encoding="utf-8")
        print("STOP: one real apply sent")
        break

if not sent:
    COUNT_FILE.write_text(str(old_count) + "\n", encoding="utf-8")
    print("STOP: no real apply sent")

print()
print("---- RESULT ----")
print("sent:", int(sent))
print("apply count:", COUNT_FILE.read_text(encoding="utf-8").strip())

print()
print("---- LETTER / POST LOG ----")
log = LOG.read_text(encoding="utf-8", errors="ignore")
shown = False

for line in log.splitlines():
    if "with params:" not in line:
        continue
    if "'message':" not in line:
        continue

    print(line[-3000:])
    shown = True

if not shown:
    for line in log.splitlines():
        if "Отправили отклик" in line or "POST" in line or "message" in line or "AI cover letter" in line:
            print(line[-3000:])

print()
print("---- SAFE SEND CHECK ----")
if sent:
    print("REAL APPLY SENT: 1")
else:
    print("REAL APPLY SENT: 0")
