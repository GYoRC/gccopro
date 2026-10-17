#!/bin/bash
# Start the Waitress server unless it is already running. Safe to call repeatedly:
# DSM Task Scheduler runs it at boot and every 5 minutes as a watchdog.
. "$(dirname "$0")/env.sh"

# Already running? Check the PID is alive and really is our waitress process.
if [ -f "$PIDFILE" ]; then
  pid="$(cat "$PIDFILE")"
  if [ -r "/proc/$pid/cmdline" ] && tr '\0' ' ' < "/proc/$pid/cmdline" | grep -q waitress-serve; then
    exit 0
  fi
fi

mkdir -p "$LOGS"
cd "$APP"
# Listen on localhost only; DSM's reverse proxy (nginx, 127.0.0.1) terminates HTTPS.
nohup "$VENV/bin/waitress-serve" \
  --listen="127.0.0.1:$PORT" \
  --threads=4 \
  --trusted-proxy=127.0.0.1 \
  --trusted-proxy-headers="x-forwarded-for x-forwarded-proto x-forwarded-host" \
  --clear-untrusted-proxy-headers \
  --call gccpro:create_app \
  >> "$LOGS/server.log" 2>&1 &
echo $! > "$PIDFILE"
echo "$(date '+%F %T') started (pid $!)" >> "$LOGS/server.log"
