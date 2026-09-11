#!/bin/bash
set -euo pipefail

ACTION="${1:-}"

if [[ -z "$ACTION" ]]; then
  echo "Usage: $0 <start|stop|status|restart>"
  exit 1
fi

# Mailpit / local SMTP
MAILPIT_BIN="${MAILPIT_BIN:-$(command -v mailpit || command -v ./mailpit || echo /opt/homebrew/bin/mailpit)}"
MAILPIT_PID="/tmp/mailpit.pid"

start_email() {
  echo "Starting Mailpit (SMTP)..."
  if [[ ! -f "$MAILPIT_BIN" ]]; then
    echo "Error: mailpit not found. Install with: brew install axllent/mailpit/mailpit"
    exit 1
  fi
  nohup "$MAILPIT_BIN" >/tmp/mailpit.log 2>&1 &
  echo $! > "$MAILPIT_PID"
  sleep 1
  if kill -0 "$(cat "$MAILPIT_PID")" 2>/dev/null; then
    echo "OK (PID $(cat "$MAILPIT_PID"))"
  else
    echo "FAILED"
    rm -f "$MAILPIT_PID"
  fi
}

stop_email() {
  echo "Stopping Mailpit..."
  if [[ -f "$MAILPIT_PID" ]]; then
    kill "$(cat "$MAILPIT_PID")" 2>/dev/null || true
    rm -f "$MAILPIT_PID"
  fi
  pkill -f "mailpit" 2>/dev/null || true
  echo "OK"
}

status_email() {
  if pgrep -f "mailpit" >/dev/null 2>&1; then
    echo "Mailpit: RUNNING (PID $(pgrep -f mailpit | head -1))"
    echo "Web UI: http://localhost:8025"
  else
    echo "Mailpit: STOPPED"
  fi
}

case "$ACTION" in
  start)  start_email ;;
  stop)   stop_email ;;
  status) status_email ;;
  restart)
    stop_email
    sleep 1
    start_email
    ;;
  *)
    echo "Unknown action: $ACTION"
    exit 1
    ;;
esac
