#!/usr/bin/env bash
set -euo pipefail

cd /opt/hh-bot
mkdir -p /opt/hh-bot/logs /opt/hh-bot/state

exec flock -n /opt/hh-bot/state/reply_once.lock bash -lc '
  echo "===== $(date "+%F %T") reply timer start =====" >> /opt/hh-bot/logs/reply-timer.log

  /opt/hh-bot/venv/bin/python /opt/hh-bot/send_human_answers.py >> /opt/hh-bot/logs/reply-timer.log 2>&1 || true

  /opt/hh-bot/venv/bin/python /opt/hh-bot/autoreply_safe_questions.py >> /opt/hh-bot/logs/reply-timer.log 2>&1 || true

  HH_REPLY_MAX_PAGES=10 NO_RANDOM_SLEEP=1 timeout 180s /opt/hh-bot/reply.sh >> /opt/hh-bot/logs/reply-timer.log 2>&1 || true

  echo "===== $(date "+%F %T") reply timer end =====" >> /opt/hh-bot/logs/reply-timer.log
'
