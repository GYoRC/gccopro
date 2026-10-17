#!/bin/bash
# Stop the Waitress server started by start.sh, waiting up to 10 seconds.
. "$(dirname "$0")/env.sh"

[ -f "$PIDFILE" ] || exit 0
pid="$(cat "$PIDFILE")"
if kill -0 "$pid" 2>/dev/null; then
  kill "$pid"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  kill -9 "$pid" 2>/dev/null || true
fi
rm -f "$PIDFILE"
