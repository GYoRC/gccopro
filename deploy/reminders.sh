#!/bin/bash
# Daily job (DSM Task Scheduler, 18:00): send trash and unbooked-week reminders.
. "$(dirname "$0")/env.sh"
cd "$APP"
{
  echo "=== $(date '+%F %T')"
  "$VENV/bin/flask" send-reminders "$@"
} >> "$LOGS/reminders.log" 2>&1
