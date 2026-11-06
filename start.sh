#!/bin/bash

PGCTL="/opt/homebrew/opt/postgresql@18/bin/pg_ctl"

PRIMARY_DIR="/Users/harysrifai/data5006"
SECONDARY_DIR="/Users/harysrifai/data5008"

show_status() {
    echo ""
    echo "=== PostgreSQL Status ==="

    $PGCTL -D "$PRIMARY_DIR" status
    echo ""

    $PGCTL -D "$SECONDARY_DIR" status
    echo ""

    echo "=== Port Check ==="
    lsof -iTCP:5006 -sTCP:LISTEN 2>/dev/null
    lsof -iTCP:5008 -sTCP:LISTEN 2>/dev/null
}

start_primary() {
    $PGCTL -D "$PRIMARY_DIR" start
}

stop_primary() {
    $PGCTL -D "$PRIMARY_DIR" stop
}

restart_primary() {
    $PGCTL -D "$PRIMARY_DIR" restart
}

start_secondary() {
    $PGCTL -D "$SECONDARY_DIR" start
}

stop_secondary() {
    $PGCTL -D "$SECONDARY_DIR" stop
}

restart_secondary() {
    $PGCTL -D "$SECONDARY_DIR" restart
}

start_all() {
    $PGCTL -D "$PRIMARY_DIR" start
    sleep 3
    $PGCTL -D "$SECONDARY_DIR" start
}

stop_all() {
    $PGCTL -D "$SECONDARY_DIR" stop
    sleep 2
    $PGCTL -D "$PRIMARY_DIR" stop
}

restart_all() {
    stop_all
    sleep 3
    start_all
}

while true
do
clear

echo "===================================="
echo " PostgreSQL Replication Manager"
echo "===================================="
echo "1. Start Primary (5006)"
echo "2. Stop Primary (5006)"
echo "3. Restart Primary (5006)"
echo "4. Start Secondary (5008)"
echo "5. Stop Secondary (5008)"
echo "6. Restart Secondary (5008)"
echo "7. Start All"
echo "8. Stop All"
echo "9. Restart All"
echo "10. Status"
echo "0. Exit"
echo "===================================="

read -p "Select Menu : " menu

case $menu in
1) start_primary ;;
2) stop_primary ;;
3) restart_primary ;;
4) start_secondary ;;
5) stop_secondary ;;
6) restart_secondary ;;
7) start_all ;;
8) stop_all ;;
9) restart_all ;;
10) show_status ;;
0) exit 0 ;;
*) echo "Invalid Menu" ;;
esac

echo ""
read -p "Press ENTER..."
done
