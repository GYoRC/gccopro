#!/bin/bash
# Nightly job (DSM Task Scheduler): consistent copy of the database, kept 30 days.
# data/backups/ should be included in a Hyper Backup task for off-NAS copies.
. "$(dirname "$0")/env.sh"
cd "$APP"
"$VENV/bin/flask" backup "$DATA/backups/gccpro-$(date +%F).db" >> "$LOGS/backup.log" 2>&1
find "$DATA/backups" -name 'gccpro-*.db' -mtime +30 -delete
