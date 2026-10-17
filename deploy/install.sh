#!/bin/bash
# Run on the NAS after each deploy: create/update the virtualenv, then restart the server.
# The database schema is migrated automatically when the app starts.
set -euo pipefail
. "$(dirname "$0")/env.sh"

if [ ! -x "$VENV/bin/python" ]; then
  "$PYTHON312" -m venv "$VENV"
fi
"$VENV/bin/pip" install -q --disable-pip-version-check -r "$APP/requirements.txt"

mkdir -p "$DATA/backups" "$LOGS"
chmod 700 "$DATA"
chmod +x "$APP"/deploy/*.sh

if [ ! -f "$GCCPRO_CONFIG" ]; then
  echo "Missing $GCCPRO_CONFIG: create it from deploy/config.example.toml, then rerun." >&2
  exit 1
fi
chmod 600 "$GCCPRO_CONFIG"

"$APP/deploy/stop.sh"
"$APP/deploy/start.sh"
sleep 3
if curl -fsS -o /dev/null "http://127.0.0.1:$PORT/connexion"; then
  echo "GCCopro is running on 127.0.0.1:$PORT"
else
  echo "GCCopro did not answer; see $LOGS/server.log" >&2
  tail -20 "$LOGS/server.log" >&2
  exit 1
fi
