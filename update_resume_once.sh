#!/usr/bin/env bash
set -euo pipefail
cd /opt/hh-bot
mkdir -p /opt/hh-bot/logs
echo "===== $(date '+%F %T') resume update start =====" >> /opt/hh-bot/logs/resume-update.log
/opt/hh-bot/venv/bin/hh-applicant-tool update-resumes >> /opt/hh-bot/logs/resume-update.log 2>&1 || true
echo "===== $(date '+%F %T') resume update end =====" >> /opt/hh-bot/logs/resume-update.log
