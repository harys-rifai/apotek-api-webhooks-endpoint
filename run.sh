#!/bin/zsh
# run.sh — Jalankan ApotekMonitor di port 8090

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PORT=8090
# Kill any existing process on this port to avoid "port already in use"
PIDS=$(lsof -ti ":$PORT" 2>/dev/null || true)
if [ -n "$PIDS" ]; then
  echo "Freeing port $PORT (PID: $PIDS)..."
  kill -9 $PIDS 2>/dev/null || true
  sleep 1
fi


# Pilih Python: prioritas python3.11 dari Homebrew
if command -v /opt/homebrew/bin/python3.11 &>/dev/null; then
    PYTHON=/opt/homebrew/bin/python3.11
elif command -v python3.11 &>/dev/null; then
    PYTHON=python3.11
elif command -v python3 &>/dev/null; then
    PYTHON=python3
else
    echo "ERROR: Python 3.11+ tidak ditemukan. Install via: brew install python@3.11"
    exit 1
fi

echo "Menggunakan: $($PYTHON --version)"

# Deteksi atau buat virtualenv
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "Membuat virtualenv baru dengan $PYTHON ..."
    $PYTHON -m venv venv
    source venv/bin/activate
    echo "Upgrade pip..."
    pip install --upgrade pip -q
fi

# Pastikan dependencies terinstall
echo "Memeriksa dependencies..."
pip install -r requirements.txt -q

# Set DJANGO_SETTINGS_MODULE
export DJANGO_SETTINGS_MODULE=config.settings

# Jalankan migrasi
echo "Menjalankan migrasi database..."
python manage.py migrate --run-syncdb

# Buat superuser default jika belum ada
echo "Memeriksa user admin..."
python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@apotek.local', 'admin')
    print('Superuser admin dibuat (password: admin)')
else:
    print('User admin sudah ada')
"

echo ""
echo "======================================"
echo "  ApotekMonitor berjalan di port 8090"
echo "  URL  : http://127.0.0.1:8090"
echo "  Login: admin / admin"
echo "======================================"
echo ""

python manage.py runserver 8090
