#!/usr/bin/env bash
set -euo pipefail

cd /opt/hh-bot
source /opt/hh-bot/venv/bin/activate

SEARCH="${1:-Python Backend}"
EXP="${2:-noExperience}"
MODE="${3:-ekb}"

if [ "$MODE" = "remote" ]; then
  PLACE_ARGS=(--schedule remote)
else
  PLACE_ARGS=(--area 3)
fi

hh-applicant-tool apply-vacancies \
  --search "$SEARCH" \
  --resume-id a89be050ff10a4a4fc0039ed1f786946636470 \
  "${PLACE_ARGS[@]}" \
  --experience "$EXP" \
  --only-with-salary \
  --salary 45000 \
  --currency RUR \
  --order-by publication_time \
  --period 14 \
  --per-page 10 \
  --total-pages 1 \
  --letter-file /opt/hh-bot/fallback_letter.txt \
  --force-message \
  --no-ai \
  --no-send-email \
  --excluded-filter "Senior|Middle|Lead|Team Lead|Architect|Архитектор|Ведущий|Руководитель|директор|продажи|колл.?центр|call.?center|оператор|техподдержка|поддержка пользователей|1.?я линия|helpdesk|неоплачиваем|релокац|переезд|вахта|командировк|Елабуга|Татарстан|C\+\+|Qt|QML|STM32|микроконтрол|embedded|SDR|DSP|BIM|Revit|AutoCAD|робототех|АСУ ТП|ПЛК|frontend|фронтенд|React|Java|C#|1С|Bitrix|битрикс|VB.NET|ASP.NET|\.NET"
