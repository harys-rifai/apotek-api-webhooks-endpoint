#!/bin/bash
# run.sh — ApotekMonitor startup script (cross-platform: macOS/Linux/Windows-WSL)
#
# Flow:
#   1. Find Python 3.11+ (Homebrew, pyenv, system)
#   2. Create/reuse virtualenv
#   3. Install dependencies from requirements.txt
#   4. Auto-configure .env from .env.example if missing
#   5. Detect available PostgreSQL port (5006→5008→5007→5009→5432)
#      → update .env DB_PORT and ConnectionConfig table
#   6. Run migrations + ensure DB exists
#   7. Create admin superuser + seed endpoints (first run only)
#   8. Start Django dev server on port 8090

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Colors ───────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
    GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'
else
    GREEN=''; YELLOW=''; CYAN=''; RED=''; NC=''
fi

# ── Find Python ─────────────────────────────────────────────────────────────
PYTHON=""
for candidate in python3.12 python3.11 python3 python; do
    if command -v "$candidate" &>/dev/null; then
        PYTHON="$candidate"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    echo "${RED}ERROR: Python 3.11+ not found. Install via:brew install python@3.11${NC}"
    exit 1
fi
echo "${CYAN}[1/8]${NC} Python: $($PYTHON --version)"

# ── Kill existing process on 8090 ───────────────────────────────────────────
PORT=8090
PIDS=$(lsof -ti ":$PORT" 2>/dev/null || true)
if [ -n "$PIDS" ]; then
    echo "${YELLOW}Freeing port $PORT (PID: $PIDS)...${NC}"
    kill -9 $PIDS 2>/dev/null || true
    sleep 1
fi

# ── Create/reuse virtualenv ─────────────────────────────────────────────────
VENV_DIR="$SCRIPT_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "${CYAN}[2/8]${NC} Creating virtualenv..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

if [ -f "$VENV_DIR/Scripts/python.exe" ]; then
    VENV_PYTHON="$VENV_DIR/Scripts/python.exe"
elif [ -f "$VENV_DIR/bin/python3" ]; then
    VENV_PYTHON="$VENV_DIR/bin/python3"
else
    VENV_PYTHON="$VENV_DIR/bin/python"
fi
echo "${CYAN}[3/8]${NC} Venv Python: $("$VENV_PYTHON" --version)"

# ── Install dependencies ────────────────────────────────────────────────────
echo "${CYAN}[4/8]${NC} Installing dependencies..."
"$VENV_PYTHON" -m pip install -r "$SCRIPT_DIR/requirements.txt" --quiet --disable-pip-version-check

# ── Auto-configure .env ─────────────────────────────────────────────────────
ENV_FILE="$SCRIPT_DIR/.env"
ENV_EXAMPLE="$SCRIPT_DIR/.env.example"
if [ ! -f "$ENV_FILE" ]; then
    echo "${CYAN}[5/8]${NC} Creating .env from .env.example..."
    if [ -f "$ENV_EXAMPLE" ]; then
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        echo "${GREEN}  .env created${NC}"
    else
        printf 'SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")\nDEBUG=True\nALLOWED_HOSTS=*\nAPOTEK_API_BASE_URL=http://127.0.0.1:8000/api\nAPOTEK_ADMIN_USERNAME=admin\nAPOTEK_ADMIN_PASSWORD=admin\n' > "$ENV_FILE"
        echo "${GREEN}  .env created from defaults${NC}"
    fi
else
    echo "${CYAN}[5/8]${NC} .env already exists"
fi

# ── Auto-detect PostgreSQL port ─────────────────────────────────────────────
echo "${CYAN}[6/8]${NC} Detecting PostgreSQL port..."
export DJANGO_SETTINGS_MODULE=config.settings

# Use db_port_manager to detect port, update .env, and show result
DETECTION_OUTPUT=$("$VENV_PYTHON" -c "
from config.db_port_manager import get_pg_config, update_env_port, _find_env_file
cfg = get_pg_config()
port = cfg.get('PORT', '5432')
print(port)
" 2>/dev/null || echo "none")

if [ "$DETECTION_OUTPUT" != "none" ] && [ -n "$DETECTION_OUTPUT" ]; then
    DETECTED_PORT="$DETECTION_OUTPUT"
    echo "  ${GREEN}PostgreSQL active on port $DETECTED_PORT${NC}"
    CURRENT_PORT=$(grep -E "^DB_PORT=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2 || echo "")
    if [ -n "$CURRENT_PORT" ] && [ "$CURRENT_PORT" != "$DETECTED_PORT" ]; then
        echo "  ${YELLOW}WARNING: DB_PORT changed $CURRENT_PORT → $DETECTED_PORT${NC}"
    fi
    # db_port_manager already updated the correct .env file via settings.py
else
    echo "  ${YELLOW}WARNING: No PostgreSQL port detected${NC}"
    CURRENT_PORT=$(grep -E "^DB_PORT=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2 || echo "")
    if [ -n "$CURRENT_PORT" ]; then
        echo "  Using existing DB_PORT from .env: $CURRENT_PORT"
        DETECTED_PORT="$CURRENT_PORT"
    else
        echo "  Using default port 5006 (SQLite primary will still work)"
        echo "DB_PORT=5006" >> "$ENV_FILE"
        DETECTED_PORT="5006"
    fi
fi

# ── Run migrations + DB setup ───────────────────────────────────────────────
echo "${CYAN}[7/8]${NC} Applying migrations..."
"$VENV_PYTHON" manage.py migrate --run-syncdb

# Sync .env PG config to ConnectionConfig table if PostgreSQL is available
if [ -n "$DETECTED_PORT" ]; then
    echo "  Syncing DB config to ConnectionConfig table..."
    "$VENV_PYTHON" manage.py db_sync_config 2>/dev/null || true
fi

# Seed endpoints if database is fresh
FLAG_FILE="$SCRIPT_DIR/.db_initialized"
if [ ! -f "$FLAG_FILE" ]; then
    echo "  Creating admin superuser..."
    "$VENV_PYTHON" manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@apotek.local', 'admin')
    print('  Admin user created: admin / admin')
else:
    print('  Admin user already exists')
"
    echo "  Seeding endpoints..."
    "$VENV_PYTHON" manage.py seed_endpoints 2>/dev/null || true
    touch "$FLAG_FILE"
fi

# ── Read version ────────────────────────────────────────────────────────────
VERSION="1.0.0"
if [ -f "$SCRIPT_DIR/VERSION" ]; then
    VERSION=$(cat "$SCRIPT_DIR/VERSION" | tr -d '[:space:]')
fi

# ── Start server ────────────────────────────────────────────────────────────
echo "${CYAN}[8/8]${NC}"
echo ""
echo "======================================"
echo "  ApotekMonitor v$VERSION"
echo "  http://127.0.0.1:8090"
echo "  Login: admin / admin"
echo "======================================"
echo ""
exec "$VENV_PYTHON" manage.py runserver 8090
