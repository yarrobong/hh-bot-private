#!/usr/bin/env bash
set +e

cd /opt/hh-bot || exit 1

TODAY="$(date -u +%F)"
LOG="/opt/hh-bot/logs/apply-auto-$TODAY.log"

mkdir -p /opt/hh-bot/logs /opt/hh-bot/state

{
  echo "===== $(date -u '+%F %T') smart timer start ====="
  /opt/hh-bot/venv/bin/python /opt/hh-bot/apply_smart_auto.py
  rc=$?
  echo "===== $(date -u '+%F %T') smart timer end | rc=$rc ====="
  exit "$rc"
} >> "$LOG" 2>&1
