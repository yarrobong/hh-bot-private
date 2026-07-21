import json
import os
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv("/opt/hh-bot/.env")

api_key = os.getenv("MISTRAL_API_KEY")
model = os.getenv("MISTRAL_MODEL", "mistral-small-latest")

if not api_key:
    raise RuntimeError("MISTRAL_API_KEY не найден в /opt/hh-bot/.env")

config_path = subprocess.check_output(
    ["hh-applicant-tool", "config", "-p"],
    text=True
).strip()

path = Path(config_path)
path.parent.mkdir(parents=True, exist_ok=True)

if path.exists():
    data = json.loads(path.read_text(encoding="utf-8") or "{}")
    backup = path.with_suffix(path.suffix + ".bak")
    backup.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
else:
    data = {}

common_ai = {
    "api_key": api_key,
    "base_url": "https://api.mistral.ai/v1/chat/completions",
    "model": model,
}

data["openai_cover_letter"] = {
    **common_ai,
    "temperature": 0.75,
    "max_completion_tokens": 220,
    "rate_limit": 20
}

data["openai_vacancy_filter"] = {
    **common_ai,
    "temperature": 0.1,
    "max_completion_tokens": 120,
    "rate_limit": 10
}

path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"OK: AI config saved to {path}")
