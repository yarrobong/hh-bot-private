#!/usr/bin/env bash
set -euo pipefail

cd /opt/hh-bot
source /opt/hh-bot/venv/bin/activate

RESUME_ID="a89be050ff10a4a4fc0039ed1f786946636470"

# Проверь Екатеринбург командой ниже. Скорее всего город ЕКБ = 3.
EKB_AREA="3"

DAILY_LIMIT=40
MIN_SALARY=45000

STATE_DIR="/opt/hh-bot/state"
LOG_DIR="/opt/hh-bot/logs"
FALLBACK_LETTER="/opt/hh-bot/fallback_letter.txt"

mkdir -p "$STATE_DIR" "$LOG_DIR"

TODAY="$(date '+%F')"
COUNT_FILE="$STATE_DIR/responses-$TODAY.count"
LOG_FILE="$LOG_DIR/apply-$TODAY.log"
LOCK_FILE="$STATE_DIR/apply.lock"

exec 9>"$LOCK_FILE"
flock -n 9 || {
  echo "[$(date '+%F %T')] Already running, exit" >> "$LOG_FILE"
  exit 0
}

CURRENT_COUNT="$(cat "$COUNT_FILE" 2>/dev/null || echo 0)"

if [ "$CURRENT_COUNT" -ge "$DAILY_LIMIT" ]; then
  echo "[$(date '+%F %T')] Daily limit reached: $CURRENT_COUNT/$DAILY_LIMIT" >> "$LOG_FILE"
  exit 0
fi

# Рандомная задержка, чтобы cron не бил всегда в одну секунду
if [ "${NO_RANDOM_SLEEP:-0}" = "1" ]; then
  echo "[$(date '+%F %T')] NO_RANDOM_SLEEP=1, skip random delay" >> "$LOG_FILE"
else
  DELAY=$((RANDOM % 2700))
  echo "[$(date '+%F %T')] Random delay: ${DELAY}s" >> "$LOG_FILE"
  sleep "$DELAY"
fi

MODE="${1:-ekb}"

BATCH=$((RANDOM % 4 + 5)) # 5-8 откликов за запуск
REMAIN=$((DAILY_LIMIT - CURRENT_COUNT))

if [ "$BATCH" -gt "$REMAIN" ]; then
  BATCH="$REMAIN"
fi

EXP_LIST=("noExperience" "between1And3")
EXP="${EXP_LIST[$RANDOM % ${#EXP_LIST[@]}]}"

COMMON_EXCLUDE="Senior|Middle|Middle\+|Lead|Team Lead|Architect|Архитектор|Ведущий|Руководитель|руководитель|директор|продажи|продавец|менеджер по продажам|колл.?центр|call.?center|оператор|техподдержка|поддержка пользователей|1.?я линия|первая линия|helpdesk|неоплачиваем|релокац|переезд|переезжать|переехать|Елабуга|Татарстан|очный формат работы|обязательным условием является релокация|командировк|вахта|не рассматриваем кандидатов с других городов|C\+\+|Qt|QML|STM32|микроконтрол|встраиваем|embedded|SDR|DSP|BIM|Revit|AutoCAD|робототех|АСУ ТП|ПЛК|GPIO|UART|MATLAB|Simulink|CODESYS|TIA PORTAL|фронтенд|frontend|системный администратор|инженер.робототехник"

REMOTE_EXCLUDE="$COMMON_EXCLUDE|офис.*москва|москва.*офис|гибрид.*москва|москва.*гибрид|офис.*санкт|санкт.*офис|офис.*спб|спб.*офис|приезжать.*москва|выезд.*москва"

EKB_QUERIES=(
  "Python Backend"
  "Python Django"
  "Django разработчик"
  "Backend Python"
  "Разработчик Python"
  "Python автоматизация"
  "автоматизация CRM Python"
  "боты Python"
  "AI автоматизация"
  "ИИ автоматизация"
)

REMOTE_QUERIES=(
  "Python Backend"
  "Python Django"
  "Backend Python"
  "Python automation"
  "AI automation"
  "ИИ автоматизация"
  "нейросети автоматизация"
  "боты Python"
  "low-code automation"
  "no-code automation"
  "вайбкодер"
  "vibe coder"
)

AI_SYSTEM="Ты пишешь короткие сопроводительные письма для HeadHunter на русском. Ответ только текстом письма: без темы, без подписи, без Markdown, без списков, без плейсхолдеров. Максимум 400 символов. Нельзя выдумывать опыт, которого нет. Нельзя писать, что Ярослав работал с C++, Qt, STM32, микроконтроллерами, BIM, Revit, AutoCAD, робототехникой, DSP/SDR, GPIO/UART, если это не указано в фактах кандидата. Нельзя использовать слова: начинающий, junior, без опыта. Реальные факты: Python, Django, SQL, Git, Linux, автоматизация CRM, боты, AI-инструменты, сайт и процессы Bizon VR. Если вакансия не идеально совпадает, аккуратно связывай только реальные навыки с задачами вакансии. Не пиши ложь."

if [ "$MODE" = "remote" ]; then
  QUERY="${REMOTE_QUERIES[$RANDOM % ${#REMOTE_QUERIES[@]}]}"
  FILTER="$REMOTE_EXCLUDE"
  LOCATION_PROMPT="Это удалённая вакансия. Укажи готовность к удалённой работе."
  EXTRA_ARGS=(--schedule remote --ai-filter light --ai-rate-limit 10)

else
  QUERY="${EKB_QUERIES[$RANDOM % ${#EKB_QUERIES[@]}]}"
  FILTER="$COMMON_EXCLUDE"
  LOCATION_PROMPT="Это вакансия в Екатеринбурге. Укажи, что Ярослав находится в Екатеринбурге и готов к офису или гибриду."
  EXTRA_ARGS=(--area "$EKB_AREA")
fi

AI_PROMPT="Напиши персональное сопроводительное письмо под конкретную вакансию. Используй компанию, название вакансии, требования, обязанности и ключевые навыки из контекста. Пиши только о реальном опыте Ярослава: Python/Django, SQL, Git, Linux, автоматизация CRM, боты, AI-инструменты, технические задачи, сайт и процессы Bizon VR. Не приписывай опыт с технологиями вакансии, если их нет в фактах кандидата. Не пиши про C++, Qt, STM32, микроконтроллеры, BIM, Revit, AutoCAD, робототехнику, DSP/SDR как про опыт Ярослава. ${LOCATION_PROMPT} В конце мягко укажи готовность быстро выйти на связь."

TMP_OUTPUT="$(mktemp)"

{
  echo "============================================================"
  echo "START: $(date '+%F %T')"
  echo "MODE: $MODE"
  echo "QUERY: $QUERY"
  echo "EXPERIENCE: $EXP"
  echo "BATCH: $BATCH"
  echo "CURRENT_COUNT: $CURRENT_COUNT/$DAILY_LIMIT"
  echo "============================================================"
} >> "$LOG_FILE"

set +e

hh-applicant-tool apply-vacancies \
  --resume-id "$RESUME_ID" \
  --search "$QUERY" \
  --experience "$EXP" \
  --force-message \
  --ai \
  --ai-system "$AI_SYSTEM" \
  --prompt "$AI_PROMPT" \
  --letter-file "$FALLBACK_LETTER" \
  --only-with-salary \
  --salary "$MIN_SALARY" \
  --currency RUR \
  --order-by publication_time \
  --period 14 \
  --per-page "$BATCH" \
  --total-pages 1 \
  --excluded-filter "$FILTER" \
  "${EXTRA_ARGS[@]}" 2>&1 | tee "$TMP_OUTPUT" >> "$LOG_FILE"

STATUS="${PIPESTATUS[0]}"
set -e

SENT="$(grep -c "Отправили отклик" "$TMP_OUTPUT" || true)"
NEW_COUNT=$((CURRENT_COUNT + SENT))
echo "$NEW_COUNT" > "$COUNT_FILE"

{
  echo "SENT_THIS_RUN: $SENT"
  echo "NEW_COUNT: $NEW_COUNT/$DAILY_LIMIT"
  echo "STATUS: $STATUS"
  echo "END: $(date '+%F %T')"
  echo
} >> "$LOG_FILE"

rm -f "$TMP_OUTPUT"

exit "$STATUS"
