#!/bin/bash
set -euo pipefail

if [ -z "${BASH_VERSION:-}" ]; then
  exec /bin/bash "$0" "$@"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

run_service() {
  local service="$1"
  local action="$2"
  shift 2 || true
  local script
  case "$service" in
    monitor|apotek)
      script="$SCRIPT_DIR/api.sh"
      bash "$script" "$service" "$action" "$@"
      return
      ;;
    *)
      script="$SCRIPT_DIR/${service}.sh"
      ;;
  esac
  if [[ ! -f "$script" ]]; then
    printf '%b\n' "${RED}Error: script not found: $script${NC}"
    return 1
  fi
  chmod +x "$script"
  bash "$script" "$action" "$@"
}

show_status() {
  printf '%b\n' "${CYAN}=== Service Status ===${NC}"
  run_service postgres status 5006 || true
  run_service postgres status 5008 || true
  run_service redis status || true
  run_service email status || true
  run_service monitor status || true
  run_service apotek status || true
}

menu() {
  clear
  printf '%b\n' "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
  printf '%b\n' "${CYAN}║${NC}          ${GREEN}ApotekMonitor Service Manager${NC}                ${CYAN}║${NC}"
  printf '%b\n' "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
  echo ""
  printf '%b\n' "${YELLOW}1)${NC} Start all services"
  printf '%b\n' "${YELLOW}2)${NC} Stop all services"
  printf '%b\n' "${YELLOW}3)${NC} Restart all services"
  printf '%b\n' "${YELLOW}4)${NC} Show status"
  echo ""
  printf '%b\n' "${CYAN}--- Individual Services ---${NC}"
  printf '%b\n' "${YELLOW}5)${NC} PostgreSQL Primary (5006)"
  printf '%b\n' "${YELLOW}6)${NC} PostgreSQL Secondary (5008)"
  printf '%b\n' "${YELLOW}7)${NC} Redis"
  printf '%b\n' "${YELLOW}8)${NC} Email (Mailpit)"
  printf '%b\n' "${YELLOW}9)${NC} ApotekMonitor API (8090)"
  printf '%b\n' "${YELLOW}10)${NC} ApotekApps API (8000)"
  echo ""
  printf '%b\n' "${RED}0)${NC} Exit"
  echo ""
  read -p "Choose [0-10]: " choice
  echo ""

  case "$choice" in
    1)
      printf '%b\n' "${GREEN}Starting all services...${NC}"
      run_service postgres start 5006
      run_service postgres start 5008
      run_service redis start
      run_service email start
      run_service apotek start
      run_service monitor start
      printf '%b\n' "${GREEN}All services started${NC}"
      ;;
    2)
      printf '%b\n' "${YELLOW}Stopping all services...${NC}"
      run_service monitor stop
      run_service apotek stop
      run_service email stop
      run_service redis stop
      run_service postgres stop 5006
      run_service postgres stop 5008
      printf '%b\n' "${YELLOW}All services stopped${NC}"
      ;;
    3)
      printf '%b\n' "${YELLOW}Restarting all services...${NC}"
      run_service monitor restart
      run_service apotek restart
      run_service email restart
      run_service redis restart
      run_service postgres restart 5006
      run_service postgres restart 5008
      printf '%b\n' "${GREEN}All services restarted${NC}"
      ;;
    4)
      show_status
      ;;
    5)
      printf '%b\n' "${CYAN}PostgreSQL Primary (5006)${NC}"
      echo "1) Start  2) Stop  3) Status  4) Restart"
      read -p "Choose [1-4]: " pg1
      case "$pg1" in
        1) run_service postgres start 5006 ;;
        2) run_service postgres stop 5006 ;;
        3) run_service postgres status 5006 ;;
        4) run_service postgres restart 5006 ;;
      esac
      ;;
    6)
      printf '%b\n' "${CYAN}PostgreSQL Secondary (5008)${NC}"
      echo "1) Start  2) Stop  3) Status  4) Restart"
      read -p "Choose [1-4]: " pg2
      case "$pg2" in
        1) run_service postgres start 5008 ;;
        2) run_service postgres stop 5008 ;;
        3) run_service postgres status 5008 ;;
        4) run_service postgres restart 5008 ;;
      esac
      ;;
    7)
      printf '%b\n' "${CYAN}Redis${NC}"
      echo "1) Start  2) Stop  3) Status  4) Restart"
      read -p "Choose [1-4]: " rd
      case "$rd" in
        1) run_service redis start ;;
        2) run_service redis stop ;;
        3) run_service redis status ;;
        4) run_service redis restart ;;
      esac
      ;;
    8)
      printf '%b\n' "${CYAN}Email (Mailpit)${NC}"
      echo "1) Start  2) Stop  3) Status  4) Restart"
      read -p "Choose [1-4]: " em
      case "$em" in
        1) run_service email start ;;
        2) run_service email stop ;;
        3) run_service email status ;;
        4) run_service email restart ;;
      esac
      ;;
    9)
      printf '%b\n' "${CYAN}ApotekMonitor API (8090)${NC}"
      echo "1) Start  2) Stop  3) Status  4) Restart"
      read -p "Choose [1-4]: " mon
      case "$mon" in
        1) run_service monitor start ;;
        2) run_service monitor stop ;;
        3) run_service monitor status ;;
        4) run_service monitor restart ;;
      esac
      ;;
    10)
      printf '%b\n' "${CYAN}ApotekApps API (8000)${NC}"
      echo "1) Start  2) Stop  3) Status  4) Restart"
      read -p "Choose [1-4]: " apt
      case "$apt" in
        1) run_service apotek start ;;
        2) run_service apotek stop ;;
        3) run_service apotek status ;;
        4) run_service apotek restart ;;
      esac
      ;;
    0)
      echo "Bye."
      exit 0
      ;;
    *)
      printf '%b\n' "${RED}Invalid choice${NC}"
      ;;
  esac

  echo ""
  read -p "Press Enter to continue..."
  menu
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  if [[ $# -gt 0 ]]; then
    # Non-interactive mode for backward compatibility
    CMD="$1"
    shift || true
    case "$CMD" in
      start|stop|status|restart)
        if [[ "$CMD" == "start" ]]; then
          run_service postgres start 5006
          run_service postgres start 5008
          run_service redis start
          run_service email start
          run_service apotek start
          run_service monitor start
        elif [[ "$CMD" == "stop" ]]; then
          run_service monitor stop
          run_service apotek stop
          run_service email stop
          run_service redis stop
          run_service postgres stop 5006
          run_service postgres stop 5008
        elif [[ "$CMD" == "restart" ]]; then
          run_service monitor restart
          run_service apotek restart
          run_service email restart
          run_service redis restart
          run_service postgres restart 5006
          run_service postgres restart 5008
        elif [[ "$CMD" == "status" ]]; then
          show_status
        fi
        ;;
      postgres|redis|email|monitor|apotek)
        if [[ $# -lt 1 ]]; then
          echo "Error: action required"
          exit 1
        fi
        run_service "$CMD" "$1" "${@:2}"
        ;;
      *)
        echo "Usage: $0 [start|stop|restart|status|<service> <action>]"
        exit 1
        ;;
    esac
  else
    menu
  fi
fi
