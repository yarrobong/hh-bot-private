#!/usr/bin/env bash
set -euo pipefail

cd /opt/hh-bot
: > /home/hhbot/.config/hh-applicant-tool/log.txt

SYSTEM_PROMPT="$(cat /opt/hh-bot/cover_letter_system_prompt.txt)"
MESSAGE_PROMPT="$(cat /opt/hh-bot/cover_letter_message_prompt.txt)"

timeout 180s /opt/hh-bot/venv/bin/hh-applicant-tool apply-vacancies \
  --resume-id a89be050ff10a4a4fc0039ed1f786946636470 \
  --search "Python" \
  --area 3 \
  --experience noExperience \
  --salary 45000 \
  --period 30 \
  --per-page 20 \
  --total-pages 1 \
  --use-ai \
  --system-prompt "$SYSTEM_PROMPT" \
  --message-prompt "$MESSAGE_PROMPT" \
  --force-message \
  --no-send-email \
  --dry-run

echo
echo "---- CHECK REAL SEND ----"
if grep -q "201 POST https://api.hh.ru/negotiations/.*/messages" /home/hhbot/.config/hh-applicant-tool/log.txt; then
  echo "BAD: real message sent"
else
  echo "OK: dry-run did not send"
fi

echo
echo "---- AI / LETTER LOG ----"
grep -E "AI системный промпт|AI .*ответ|Ошибка AI|Ошибка OpenAI|message|dry" /home/hhbot/.config/hh-applicant-tool/log.txt | tail -n 180 || true
