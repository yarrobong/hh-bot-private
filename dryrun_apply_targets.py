from pathlib import Path
import subprocess
import re
import shlex

ROOT = Path("/opt/hh-bot")
LOG = Path("/home/hhbot/.config/hh-applicant-tool/log.txt")

script = (ROOT / "apply_campaign_safe.sh").read_text(encoding="utf-8", errors="ignore")
m = re.search(r'EXCLUDED_FILTER="([^"]*)"', script)
excluded = m.group(1) if m else ""

system_prompt = (ROOT / "cover_letter_system_prompt.txt").read_text(encoding="utf-8", errors="ignore")
message_prompt = (ROOT / "cover_letter_message_prompt.txt").read_text(encoding="utf-8", errors="ignore")

targets = []
for line in (ROOT / "apply_targets.txt").read_text(encoding="utf-8", errors="ignore").splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    parts = line.split("|", 2)
    if len(parts) == 3:
        targets.append(parts)

LOG.write_text("", encoding="utf-8")

print("targets:", len(targets))
print("excluded filter loaded:", bool(excluded))
print()

for i, (mode, exp, search) in enumerate(targets[:18], 1):
    print()
    print("=" * 90)
    print(f"{i}. mode={mode} exp={exp} search={search}")
    print("=" * 90)

    cmd = [
        "/opt/hh-bot/venv/bin/hh-applicant-tool",
        "apply-vacancies",
        "--resume-id", "a89be050ff10a4a4fc0039ed1f786946636470",
        "--search", search,
        "--experience", exp,
        "--salary", "45000",
        "--period", "30",
        "--per-page", "8",
        "--total-pages", "1",
        "--use-ai",
        "--system-prompt", system_prompt,
        "--message-prompt", message_prompt,
        "--force-message",
        "--no-send-email",
        "--excluded-filter", excluded,
        "--dry-run",
    ]

    if mode == "ekb":
        cmd += ["--area", "3"]
    elif mode == "remote":
        cmd += ["--schedule", "remote"]

    try:
        r = subprocess.run(
            cmd,
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
        print(r.stdout)
    except subprocess.TimeoutExpired:
        print("[TIMEOUT]")
    except Exception as e:
        print("[ERROR]", repr(e))

print()
print("---- CHECK SEND ----")
log = LOG.read_text(encoding="utf-8", errors="ignore")
if "201 POST https://api.hh.ru/negotiations/" in log and "/messages" in log:
    print("BAD: real message sent")
else:
    print("OK: dry-run did not send")

print()
print("---- FOUND / WARNINGS ----")
patterns = [
    "Вакансия:",
    "AI cover letter replaced",
    "unsafe claim",
    "Отправлено",
    "Пришел отказ",
    "DEBUG - Здравствуйте",
    "DEBUG - Привет",
]
lines = []
for line in log.splitlines():
    if any(p in line for p in patterns):
        lines.append(line)

for line in lines[-220:]:
    print(line)
