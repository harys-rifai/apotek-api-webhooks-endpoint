#!/bin/bash
# pg_failover.sh — Unified PostgreSQL switchover / failover / repair script
#
# Detects primary & standby across ports 5006/5008, then offers:
#   [1] Status   — show role (primary/standby) + replication health of each
#   [2] Failover  — promote standby → new primary, stop old primary
#   [3] Rebuild   — pg_basebackup new standby from current primary
#   [4] Repair    — full cycle: failover + rebuild old primary as standby
#   [5] Swing DB  — update .env DB_PORT to point at the new primary
#   [0] Exit
#
set -euo pipefail

PGHOME="${PGHOME:-C:\Program Files\PostgreSQL\18}"
# On Unix, PGHOME is usually a Homebrew or Linux path
if [ ! -d "$PGHOME" ]; then
    if [ -d "/opt/homebrew/opt/postgresql@18" ]; then
        PGHOME="/opt/homebrew/opt/postgresql@18"
    elif [ -d "/usr/lib/postgresql/18" ]; then
        PGHOME="/usr/lib/postgresql/18"
    elif [ -d "/usr/local/pgsql" ]; then
        PGHOME="/usr/local/pgsql"
    fi
fi

PSQL="$PGHOME/bin/psql"
PG_BASEBACKUP="$PGHOME/bin/pg_basebackup"
PG_CTL="$PGHOME/bin/pg_ctl"

# Ports: primary=5006, standby=5008
PRIMARY_PORT=5006
STANDBY_PORT=5008
REPL_USER="${REPLICA_USER:-replicator}"
REPL_PASSWORD="${REPL_PASSWORD:-Password09!}"
PG_USER="${PG_USER:-postgres}"
PG_PASSWORD="${PG_PASSWORD:-Password09!}"
DATA_DIR_5006="${DATA_DIR_5006:-C:\PostgreSQL\data5006}"
DATA_DIR_5008="${DATA_DIR_5008:-C:\PostgreSQL\data5008}"

# Map to services (adjust names if needed)
SVC_5006="${PG_SERVICE_5006:-postgresql-x64-18-5006}"
SVC_5008="${PG_SERVICE_5008:-postgresql-x64-18-5008}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

run_psql() {
    local port="$1"; shift
    PGPASSWORD="$PG_PASSWORD" "$PSQL" -h 127.0.0.1 -p "$port" -U "$PG_USER" "$@" 2>/dev/null
}

run_psql_repl() {
    local port="$1"; shift
    PGPASSWORD="$REPL_PASSWORD" "$PSQL" -h 127.0.0.1 -p "$port" -U "$REPL_USER" "$@" 2>/dev/null
}

stop_service() {
    local svc="$1"
    echo "  Stopping $svc..."
    sc stop "$svc" 2>/dev/null || true
}

start_service() {
    local svc="$1"
    echo "  Starting $svc..."
    sc start "$svc" 2>/dev/null || true
}

check_role() {
    local port="$1"
    local result
    result=$(run_psql "$port" -c "SELECT pg_is_in_recovery();" -tA 2>/dev/null || echo "offline")
    if [ "$result" = "t" ]; then
        echo "standby"
    elif [ "$result" = "f" ]; then
        echo "primary"
    else
        echo "offline"
    fi
}

check_status() {
    echo ""
    echo -e "${CYAN}===== PRIMARY ($PRIMARY_PORT) =====${NC}"
    local role
    role=$(check_role "$PRIMARY_PORT")
    if [ "$role" = "primary" ]; then
        echo -e "  Role: ${GREEN}PRIMARY${NC}"
        echo "  pg_is_in_recovery: f"
        echo "  Replication clients:"
        run_psql "$PRIMARY_PORT" -c "SELECT client_addr, state, sync_state FROM pg_stat_replication;" -t 2>/dev/null || echo "  (no replication slots)"
    elif [ "$role" = "standby" ]; then
        echo -e "  Role: ${YELLOW}STANDBY${NC} (expected primary)"
    else
        echo -e "  Role: ${RED}OFFLINE${NC}"
    fi

    echo ""
    echo -e "${CYAN}===== STANDBY ($STANDBY_PORT) =====${NC}"
    role=$(check_role "$STANDBY_PORT")
    if [ "$role" = "standby" ]; then
        echo -e "  Role: ${GREEN}STANDBY${NC}"
        echo "  pg_is_in_recovery: t"
        echo "  WAL receiver status:"
        run_psql "$STANDBY_PORT" -c "SELECT status, conninfo FROM pg_stat_wal_receiver;" -t 2>/dev/null || echo "  (no WAL receiver)"
    elif [ "$role" = "primary" ]; then
        echo -e "  Role: ${YELLOW}PRIMARY${NC} (expected standby)"
    else
        echo -e "  Role: ${RED}OFFLINE${NC}"
    fi
    echo ""
}

failover() {
    echo -e "${YELLOW}===== FAILOVER: promote standby → new primary =====${NC}"

    local standby_role
    standby_role=$(check_role "$STANDBY_PORT")
    if [ "$standby_role" != "standby" ]; then
        echo -e "${RED}ERROR: Port $STANDBY_PORT is not a standby (role=$standby_role). Aborting.${NC}"
        return 1
    fi

    echo "Step 1 - Promote standby on $STANDBY_PORT..."
    "$PG_CTL" -D "$DATA_DIR_5008" promote || {
        echo -e "${RED}Promote failed${NC}"
        return 1
    }
    echo "  Waiting for promotion to complete..."
    sleep 10

    echo "Step 2 - Stop old primary on $PRIMARY_PORT..."
    stop_service "$SVC_5006"

    echo ""
    echo -e "${GREEN}Switchover completed.${NC}"
    echo "  $STANDBY_PORT is now ${GREEN}PRIMARY${NC}"
    echo "  $PRIMARY_PORT is stopped (needs rebuild to become standby)"
    echo ""

    swing_db_port
}

rebuild_standby() {
    echo -e "${YELLOW}===== REBUILD STANDBY from primary =====${NC}"

    local primary_role
    primary_role=$(check_role "$PRIMARY_PORT")
    if [ "$primary_role" != "primary" ]; then
        echo -e "${RED}ERROR: Port $PRIMARY_PORT is not primary (role=$primary_role).${NC}"
        echo "  Promote a standby first, or run Repair."
        return 1
    fi

    echo "Step 1 - Stop standby on $STANDBY_PORT..."
    stop_service "$SVC_5008"
    sleep 2

    echo "Step 2 - Wipe old standby data..."
    rm -rf "$DATA_DIR_5008"
    mkdir -p "$DATA_DIR_5008"

    echo "Step 3 - pg_basebackup from primary ($PRIMARY_PORT)..."
    PGPASSWORD="$REPL_PASSWORD" "$PG_BASEBACKUP" \
        -h 127.0.0.1 -p "$PRIMARY_PORT" \
        -U "$REPLICA_USER" \
        -D "$DATA_DIR_5008" \
        -R -X stream -P

    echo "Step 4 - Configure recovery..."
    echo "port = $STANDBY_PORT" >> "$DATA_DIR_5008/postgresql.auto.conf"
    echo "hot_standby = on" >> "$DATA_DIR_5008/postgresql.auto.conf"

    echo "Step 5 - Start standby..."
    start_service "$SVC_5008"

    echo -e "${GREEN}Standby rebuilt on $STANDBY_PORT.${NC}"
}

repair() {
    echo -e "${YELLOW}===== FULL REPAIR: failover + rebuild =====${NC}"
    failover
    echo ""
    rebuild_standby
    echo ""
    check_status
}

swing_db_port() {
    echo -e "${CYAN}===== Swinging DB port to new primary ($STANDBY_PORT) =====${NC}"
    local env_file=""
    # Find .env
    for candidate in \
        "$SCRIPT_DIR/.env" \
        "$SCRIPT_DIR/../ApotekApps/.env"; do
        if [ -f "$candidate" ]; then
            env_file="$candidate"
            break
        fi
    done
    if [ -z "$env_file" ]; then
        env_file="$SCRIPT_DIR/.env"
        touch "$env_file"
    fi
    # Update DB_PORT in .env
    if grep -q "^DB_PORT=" "$env_file" 2>/dev/null; then
        sed -i "s/^DB_PORT=.*/DB_PORT=$STANDBY_PORT/" "$env_file"
    else
        echo "DB_PORT=$STANDBY_PORT" >> "$env_file"
    fi
    echo "  Updated .env: DB_PORT=$STANDBY_PORT"

    # Sync to ConnectionConfig table
    if [ -f "$SCRIPT_DIR/manage.py" ]; then
        (cd "$SCRIPT_DIR" && "$SCRIPT_DIR/venv/bin/python" manage.py db_sync_config 2>/dev/null) || \
        (cd "$SCRIPT_DIR" && "$SCRIPT_DIR/venv/Scripts/python.exe" manage.py db_sync_config 2>/dev/null) || true
    fi
}

menu() {
    while true; do
        echo ""
        echo -e "${CYAN}╔══════════════════════════════════════════╗${NC}"
        echo -e "${CYAN}║${NC} ${GREEN}PostgreSQL Switchover / Failover${NC}            ${CYAN}║${NC}"
        echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}"
        echo ""
        echo -e "  ${YELLOW}1)${NC} Show status (primary + standby)"
        echo -e "  ${YELLOW}2)${NC} Failover (promote $STANDBY_PORT, stop $PRIMARY_PORT)"
        echo -e "  ${YELLOW}3)${NC} Rebuild standby from primary"
        echo -e "  ${YELLOW}4)${NC} Repair (full cycle: failover + rebuild)"
        echo -e "  ${YELLOW}5)${NC} Swing DB port (.env + table)"
        echo -e "  ${RED}0)${NC} Exit"
        echo ""
        read -p "Choose [0-5]: " choice
        echo ""
        case "$choice" in
            1) check_status ;;
            2) failover ;;
            3) rebuild_standby ;;
            4) repair ;;
            5) swing_db_port ;;
            0) echo "Bye."; exit 0 ;;
            *) echo -e "${RED}Invalid choice${NC}" ;;
        esac
        read -p "Press Enter to continue..."
    done
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    if [ $# -gt 0 ]; then
        case "$1" in
            status)   check_status ;;
            failover) failover ;;
            rebuild)  rebuild_standby ;;
            repair)   repair ;;
            swing)    swing_db_port ;;
            *)
                echo "Usage: $0 [status|failover|rebuild|repair|swing]"
                exit 1
                ;;
        esac
    else
        menu
    fi
fi
