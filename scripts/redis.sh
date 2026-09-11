#!/bin/bash
set -euo pipefail

ACTION="${1:-}"

if [[ -z "$ACTION" ]]; then
  echo "Usage: $0 <start|stop|status|restart>"
  exit 1
fi

REDIS_CONF="${REDIS_CONF:-/usr/local/etc/redis.conf}"
REDIS_BIN="${REDIS_BIN:-$(command -v redis-server || echo /usr/local/bin/redis-server)}"

if [[ ! -f "$REDIS_CONF" ]]; then
  # Use Homebrew services for start/stop/restart when no local config exists.
  if command -v brew >/dev/null 2>&1; then
    case "$ACTION" in
      start)  brew services start redis; exit $? ;;
      stop)   brew services stop redis; exit $? ;;
      restart) brew services restart redis; exit $? ;;
    esac
  else
    echo "Error: redis.conf not found at $REDIS_CONF"
    exit 1
  fi
fi

start_redis() {
  echo "Starting Redis..."
  nohup "$REDIS_BIN" "$REDIS_CONF" >/tmp/redis.log 2>&1 &
  echo $! > /tmp/redis.pid
  sleep 1
  if kill -0 "$(cat /tmp/redis.pid)" 2>/dev/null; then
    echo "OK (PID $(cat /tmp/redis.pid))"
  else
    echo "FAILED"
    rm -f /tmp/redis.pid
  fi
}

stop_redis() {
  echo "Stopping Redis..."
  if [[ -f /tmp/redis.pid ]]; then
    kill "$(cat /tmp/redis.pid)" 2>/dev/null || true
    rm -f /tmp/redis.pid
  fi
  pkill -f "redis-server $REDIS_CONF" 2>/dev/null || true
  echo "OK"
}

status_redis() {
  if pgrep -f '[r]edis-server' >/dev/null 2>&1; then
    echo "Redis: RUNNING (PID $(pgrep -f '[r]edis-server' | head -1))"
    return
  fi
  if command -v brew >/dev/null 2>&1; then
    local state
    state="$(brew services list 2>/dev/null | awk '$1 == "redis" {print $2}' || true)"
    if [[ "$state" == "started" ]]; then
      echo "Redis: RUNNING"
    else
      echo "Redis: STOPPED"
    fi
    return
  fi
  echo "Redis: STOPPED"
}

case "$ACTION" in
  start)  start_redis ;;
  stop)   stop_redis ;;
  status) status_redis ;;
  restart)
    stop_redis
    sleep 1
    start_redis
    ;;
  *)
    echo "Unknown action: $ACTION"
    exit 1
    ;;
esac
