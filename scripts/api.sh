#!/bin/bash
set -euo pipefail

APP="${1:-}"
ACTION="${2:-}"

if [[ -z "$APP" || -z "$ACTION" ]]; then
  echo "Usage: $0 <monitor|apotek> <start|stop|status|restart>"
  echo "Example: $0 monitor start"
  echo "Example: $0 apotek stop"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [[ "$APP" == "monitor" ]]; then
  APP_DIR="$PROJECT_ROOT/ApotekMonitor"
  MANAGE="$APP_DIR/manage.py"
  PIDFILE="/tmp/apotek_monitor.pid"
  PORT="${MONITOR_PORT:-8090}"
elif [[ "$APP" == "apotek" ]]; then
  APP_DIR="$PROJECT_ROOT/ApotekApps"
  MANAGE="$APP_DIR/manage.py"
  PIDFILE="/tmp/apotek_apps.pid"
  PORT="${APOTEK_PORT:-8000}"
else
  echo "Unknown app: $APP"
  exit 1
fi

if [[ ! -f "$MANAGE" ]]; then
  echo "Error: manage.py not found at $MANAGE"
  exit 1
fi

start_api() {
  echo "Starting $APP API on port $PORT..."
  if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "Already running (PID $(cat "$PIDFILE"))"
    return 0
  fi
  cd "$APP_DIR"
  nohup python "$MANAGE" runserver "0.0.0.0:$PORT" > "/tmp/${APP}_api.log" 2>&1 &
  echo $! > "$PIDFILE"
  sleep 2
  if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "OK (PID $(cat "$PIDFILE"), port $PORT)"
  else
    echo "FAILED"
    rm -f "$PIDFILE"
  fi
}

stop_api() {
  echo "Stopping $APP API..."
  if [[ -f "$PIDFILE" ]]; then
    kill "$(cat "$PIDFILE")" 2>/dev/null || true
    rm -f "$PIDFILE"
  fi
  pkill -f "runserver 0.0.0.0:$PORT" 2>/dev/null || true
  echo "OK"
}

status_api() {
  if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "$APP API: RUNNING (PID $(cat "$PIDFILE"), port $PORT)"
  else
    echo "$APP API: STOPPED"
  fi
}

case "$ACTION" in
  start)  start_api ;;
  stop)   stop_api ;;
  status) status_api ;;
  restart)
    stop_api
    sleep 1
    start_api
    ;;
  *)
    echo "Unknown action: $ACTION"
    exit 1
    ;;
esac
