#!/usr/bin/env bash
set -euo pipefail

cd /opt/hh-bot
mkdir -p /opt/hh-bot/logs /opt/hh-bot/state

exec flock -n /opt/hh-bot/state/apply.lock bash -lc '
set -euo pipefail
cd /opt/hh-bot

source /opt/hh-bot/venv/bin/activate

TODAY="$(date -u +%F)"
COUNT_FILE="/opt/hh-bot/state/apply-count-$TODAY.txt"
INDEX_FILE="/opt/hh-bot/state/apply-target-index.txt"
LOG="/opt/hh-bot/logs/apply-auto-$TODAY.log"

MAX_DAILY="${APPLY_MAX_DAILY:-35}"
BATCH_SIZE="${APPLY_BATCH_SIZE:-5}"

if [ ! -f "$COUNT_FILE" ]; then
  echo 0 > "$COUNT_FILE"
fi

COUNT="$(cat "$COUNT_FILE" 2>/dev/null || echo 0)"

if [ "$COUNT" -ge "$MAX_DAILY" ]; then
  echo "===== $(date "+%F %T") daily limit reached: $COUNT / $MAX_DAILY =====" >> "$LOG"
  exit 0
fi

mapfile -t TARGETS < /opt/hh-bot/apply_targets.txt

if [ "${#TARGETS[@]}" -eq 0 ]; then
  echo "===== $(date "+%F %T") no targets =====" >> "$LOG"
  exit 0
fi

IDX="$(cat "$INDEX_FILE" 2>/dev/null || echo 0)"
LINE="${TARGETS[$((IDX % ${#TARGETS[@]}))]}"
echo $((IDX + 1)) > "$INDEX_FILE"

IFS="|" read -r MODE EXP SEARCH <<< "$LINE"

if [ "$MODE" = "remote" ]; then
  PLACE_ARGS=(--schedule remote)
else
  PLACE_ARGS=(--area 3)
fi

REMAIN=$((MAX_DAILY - COUNT))
if [ "$REMAIN" -lt "$BATCH_SIZE" ]; then
  BATCH_SIZE="$REMAIN"
fi

EXCLUDED_FILTER="Senior|Middle|Lead|Team Lead|Architect|Руководитель|директор|сопровождение клиентов|амбассадор|колл.?центр|call.?center|оператор|1.?я линия|первая линия|helpdesk|неоплачиваем|релокац|переезд|вахта|командировк|C\+\+|Qt|QML|STM32|микроконтрол|embedded|SDR|DSP|BIM|Revit|AutoCAD|робототех|АСУ ТП|ПЛК|горное дело|производство|frontend|фронтенд|React|C#|1С|1c|Bitrix|битрикс|VB.NET|ASP.NET|\.NET|DevOps|девопс|CI/CD|Kubernetes|k8s|Kafka|Golang|Go PAM|PAM|IAM|Security|Zero Trust|администрирование серверов|сисадмин|системный администратор|DBA|администратор СУБД|администратор баз|разработчик баз данных|Младший Разработчик SQL|Data Analyst|аналитик данных|Data Scientist|data scientist|ML-инженер|ML engineer|Data Engineer|дата инженер|разметчик данных|разметка данных|AI Trainer|QA|AQA|тестировщик|тестирование|тест-кейс|e2e|преподаватель|учитель|наставник|курс|ночной преподаватель|контент|контент-креатор|content creator|reels|blogger|блогер|video creator|видео|motion designer|дизайнер|коммуникационный дизайнер|ассистент руководителя|бизнес-ассистент|операционный ассистент|project manager|проектный менеджер|помощник project manager|офис-менеджер|администратор офиса|секретарь|сборка техники|диагностика техники|ремонт техники|ремонт оборудования|информационная безопасность|кибербезопас|security|инженер внедрения|инженер по внедрению|Linux / Информационная безопасность|php программист|3D Artist|3d artist|Technical Artist|technical artist|Blender|blender|Computer Vision|computer vision|CV engineer|инженер по моделированию|моделирование технических систем|php-разработчик|php разработчик|laravel|symfony|java[- ]?разработчик|разработчик java|java developer|backend java|php[- ]?разработчик|go[- ]?разработчик|разработчик go|go developer|backend go|системный аналитик|bi аналитик|dwh|продуктовый аналитик|финансовый аналитик|менеджер проектов|помощник руководителя|риелтор|недвижимост|специалист технической поддержки|специалист техподдержки|1[- ]?я линия|менеджер по продаж|специалист по продаж|sales manager|менеджер по работе с клиент|специалист по работе с клиент|бизнес[- ]?аналитик|business analyst|аналитик качества|аналитик[ -/]?консультант|аналитик[- ]автоматизатор|продуктовый[ /-]?bi аналитик|bi[- ]?аналитик|bi[- ]?разработчик|стратегическ[а-яё ]+аналитик|стрим стратегической аналитики|инженер по тестированию|qa[- ]?инженер|ручное тестирование|автоматизация тестирования|тест[- ]?кейс|check[- ]?list|чек[- ]?лист|пентестер|pentester|penetration|reverse engineer|reverse engineering|anti[- ]?detect|browser emulation|антидетект|\bИБ\b|продавать|продавайте|b2c|горячие лиды|репетитор|спикер|аудитор|внутренний аудитор|аудит|контейнеризац|docker|openshift|helm|greenplum|etl|airflow"

SYSTEM_PROMPT="$(cat /opt/hh-bot/cover_letter_system_prompt.txt)"
MESSAGE_PROMPT="$(cat /opt/hh-bot/cover_letter_message_prompt.txt)"

echo "===== $(date "+%F %T") apply start | count=$COUNT/$MAX_DAILY | mode=$MODE | exp=$EXP | search=$SEARCH | batch=$BATCH_SIZE =====" >> "$LOG"

TMP_OUTPUT="$(mktemp)"
set +e
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
  --per-page "$BATCH_SIZE" \
  --total-pages 1 \
  --use-ai \
  --system-prompt "$SYSTEM_PROMPT" \
  --message-prompt "$MESSAGE_PROMPT" \
  --force-message \
  --no-send-email \
  --excluded-filter "$EXCLUDED_FILTER" 2>&1 | tee "$TMP_OUTPUT" >> "$LOG"
RC=$?
set -e

SENT="$(grep -c "Отправили отклик на вакансию" "$TMP_OUTPUT" 2>/dev/null || true)"
case "$SENT" in
  ""|*[!0-9]*) SENT=0 ;;
esac
NEW_COUNT=$((COUNT + SENT))
echo "$NEW_COUNT" > "$COUNT_FILE"

echo "===== $(date "+%F %T") apply end | rc=$RC | actual_sent=$SENT | count=$NEW_COUNT/$MAX_DAILY =====" >> "$LOG"
rm -f "$TMP_OUTPUT"

exit 0
'
