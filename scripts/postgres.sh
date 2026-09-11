#!/bin/bash
set -euo pipefail

ACTION="${1:-}"
PORT="${2:-}"

usage() {
  echo "Usage: $0 <start|stop|status|restart> <port>"
  echo "Example: $0 start 5006"
  echo "Example: $0 stop 5008"
}

if [[ -z "$ACTION" || -z "$PORT" ]]; then
  usage
  exit 1
fi

find_pg_bin() {
  if [[ -n "${PG_BIN:-}" && -x "$PG_BIN" ]]; then
    printf '%s\n' "$PG_BIN"
    return
  fi

  if command -v pg_ctl >/dev/null 2>&1; then
    command -v pg_ctl
    return
  fi

  local candidate
  for candidate in \
    /opt/homebrew/opt/postgresql@18/bin/pg_ctl \
    /opt/homebrew/Cellar/postgresql@18/*/bin/pg_ctl \
    /usr/local/opt/postgresql@18/bin/pg_ctl \
    /usr/local/Cellar/postgresql@18/*/bin/pg_ctl; do
    if [[ -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return
    fi
  done

  echo "Error: pg_ctl not found" >&2
  return 1
}

find_data_dir() {
  local dir

  if [[ -n "${PGDATA:-}" && -f "$PGDATA/postgresql.conf" ]]; then
    printf '%s\n' "$PGDATA"
    return
  fi

  for dir in \
    /opt/homebrew/var/postgresql@18 \
    /opt/homebrew/var/postgresql@18_5006 \
    /opt/homebrew/var/postgresql@18_5008 \
    /usr/local/var/postgresql@18 \
    /usr/local/var/postgresql@18_5006 \
    /usr/local/var/postgresql@18_5008; do
    if [[ -f "$dir/postgresql.conf" ]] &&
       grep -Eq "^[[:space:]]*port[[:space:]]*=[[:space:]]*${PORT}([[:space:]]|$)" "$dir/postgresql.conf"; then
      printf '%s\n' "$dir"
      return
    fi
  done

  echo "Error: PostgreSQL data directory for port $PORT not found" >&2
  echo "Checked Homebrew paths under /opt/homebrew/var and /usr/local/var." >&2
  return 1
}

brew_service_name() {
  local candidate
  command -v brew >/dev/null 2>&1 || return 1
  if [[ "$PORT" == "5006" ]]; then
    candidates=("postgresql@18" "postgresql@18_5006" "postgresql@5006")
  else
    candidates=("postgresql@18_${PORT}" "postgresql@${PORT}")
  fi
  for candidate in "${candidates[@]}"; do
    if brew services list 2>/dev/null | awk -v name="$candidate" '$1 == name { found = 1 } END { exit(found ? 0 : 1) }'; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

PG_BIN="$(find_pg_bin)"
DATA_DIR="$(find_data_dir)"
SERVICE_NAME="$(brew_service_name || true)"

start_pg() {
  echo "Starting PostgreSQL on port $PORT..."
  if [[ -n "$SERVICE_NAME" ]]; then
    brew services start "$SERVICE_NAME" && echo "OK" || { echo "FAILED"; return 1; }
  elif "$PG_BIN" -D "$DATA_DIR" -l "$DATA_DIR/server.log" start; then
    echo "OK"
  else
    echo "FAILED"
    return 1
  fi
}

stop_pg() {
  echo "Stopping PostgreSQL on port $PORT..."
  if [[ -n "$SERVICE_NAME" ]]; then
    brew services stop "$SERVICE_NAME" && echo "OK" || { echo "FAILED"; return 1; }
  elif "$PG_BIN" -D "$DATA_DIR" -m fast stop; then
    echo "OK"
  else
    echo "FAILED"
    return 1
  fi
}

status_pg() {
  if [[ -n "$SERVICE_NAME" ]]; then
    local state
    state="$(brew services list 2>/dev/null | awk -v name="$SERVICE_NAME" '$1 == name {print $2; exit}')"
    if [[ "$state" == "started" ]]; then
      echo "PostgreSQL port $PORT: RUNNING"
    else
      echo "PostgreSQL port $PORT: STOPPED"
    fi
  elif "$PG_BIN" -D "$DATA_DIR" status >/dev/null 2>&1; then
    echo "PostgreSQL port $PORT: RUNNING"
  else
    echo "PostgreSQL port $PORT: STOPPED"
  fi
}

case "$ACTION" in
  start)  start_pg ;;
  stop)   stop_pg ;;
  status) status_pg ;;
  restart)
    stop_pg
    sleep 1
    start_pg
    ;;
  *)
    usage
    exit 1
    ;;
esac
