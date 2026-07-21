#!/usr/bin/env bash
# HH APPLY COUNTER GUARD WRAPPER
set +e

cd /opt/hh-bot || exit 1

TODAY="$(date -u +%F)"
COUNT_FILE="/opt/hh-bot/state/apply-count-$TODAY.txt"
CORE="/opt/hh-bot/apply_campaign_safe_core.sh"

mkdir -p /opt/hh-bot/state /opt/hh-bot/logs

if [ ! -f "$COUNT_FILE" ]; then
  echo 0 > "$COUNT_FILE"
fi

BEFORE="$(cat "$COUNT_FILE" 2>/dev/null || echo 0)"
case "$BEFORE" in
  ''|*[!0-9]*) BEFORE=0 ;;
esac

TMP="/tmp/hh-apply-output-$$.log"

if [ ! -x "$CORE" ]; then
  echo "BAD: core script not executable: $CORE"
  exit 1
fi

# Запускаем настоящий старый скрипт
bash "$CORE" 2>&1 | tee "$TMP"
RC="${PIPESTATUS[0]}"

# Считаем реальные отправки:
# 1) по строкам "Отправлено: N"
# 2) если таких нет, по "Отправили отклик"
SENT_BY_TOTAL="$(
  grep -oE 'Отправлено:[[:space:]]*[0-9]+' "$TMP" 2>/dev/null \
  | grep -oE '[0-9]+' \
  | awk '{s+=$1} END{print s+0}'
)"

SENT_BY_LINES="$(
  grep -c 'Отправили отклик на вакансию' "$TMP" 2>/dev/null || true
)"

if [ "$SENT_BY_TOTAL" -gt 0 ]; then
  SENT="$SENT_BY_TOTAL"
else
  SENT="$SENT_BY_LINES"
fi

case "$SENT" in
  ''|*[!0-9]*) SENT=0 ;;
esac

AFTER=$((BEFORE + SENT))
echo "$AFTER" > "$COUNT_FILE"

echo "===== counter guard | before=$BEFORE | actual_sent=$SENT | after=$AFTER | rc=$RC ====="

rm -f "$TMP"
exit "$RC"
