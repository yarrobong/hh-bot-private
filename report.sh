#!/usr/bin/env bash
set -euo pipefail

TODAY="$(date '+%F')"
LOG="/opt/hh-bot/logs/apply-$TODAY.log"
COUNT="/opt/hh-bot/state/responses-$TODAY.count"

echo "===== HH BOT REPORT $TODAY ====="

echo
echo "Откликов сегодня:"
cat "$COUNT" 2>/dev/null || echo 0

echo
echo "Последние отправленные вакансии:"
grep -E "Отправили отклик" "$LOG" 2>/dev/null | tail -n 30 || echo "Пока нет"

echo
echo "Последние запуски:"
grep -E "START:|MODE:|QUERY:|EXPERIENCE:|BATCH:|SENT_THIS_RUN|NEW_COUNT|STATUS|END:" "$LOG" 2>/dev/null | tail -n 120 || echo "Лога пока нет"

echo
echo "Подозрительные строки:"
grep -Ei "error|ошибка|traceback|exception|требуется авторизация|captcha|лимит|forbidden|unauthorized|failed|status: 1|STATUS: 1" "$LOG" 2>/dev/null | tail -n 40 || echo "Ошибок не найдено"

echo
echo "Последние 80 строк полного лога:"
tail -n 80 "$LOG" 2>/dev/null || echo "Лога пока нет"
