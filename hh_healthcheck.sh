#!/usr/bin/env bash
set -euo pipefail

mkdir -p /opt/hh-bot/logs

{
  echo "===== $(date '+%F %T') healthcheck start ====="

  systemctl start hh-ask-server.service || true
  systemctl start hh-reply-once.timer || true
  systemctl start hh-apply-auto.timer || true
  systemctl start hh-resume-update.timer || true

  systemctl is-active hh-ask-server.service || true
  systemctl is-active hh-reply-once.timer || true
  systemctl is-active hh-apply-auto.timer || true
  systemctl is-active hh-resume-update.timer || true

  echo "===== $(date '+%F %T') healthcheck end ====="
} >> /opt/hh-bot/logs/healthcheck.log 2>&1
