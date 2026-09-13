@echo off
setlocal enabledelayedexpansion

REM run.bat - ApotekMonitor startup script for Windows
REM
REM Flow:
REM   1. Find Python 3.11+ (py launcher, system python)
REM   2. Create/reuse virtualenv
REM   3. Install dependencies
REM   4. Auto-configure .env from .env.example
REM   5. Detect available PostgreSQL port (5006->5008->5007->5009->5432)
REM      -> update .env DB_PORT and ConnectionConfig table
REM   6. Run migrations
REM   7. Create admin + seed (first run only)
REM   8. Start Django dev server on port 8090

set "PROJECT_DIR=%~dp0"
set "VENV_DIR=%PROJECT_DIR%venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "ENV_FILE=%PROJECT_DIR%.env"
set "ENV_EXAMPLE=%PROJECT_DIR%.env.example"
set "FLAG_FILE=%PROJECT_DIR%.db_initialized"
set "DETECTED_PORT="
set "PYTHON_EXE="

REM ── Read version ───────────────────────────────────────────────────────────
set "VERSION=1.0.0"
if exist "%PROJECT_DIR%VERSION" (
    set /p VERSION=<"%PROJECT_DIR%VERSION"
    set VERSION=!VERSION: =!
)

REM ── Step 1: Find Python ────────────────────────────────────────────────────
echo [1/8] Finding Python

py -3.12 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1 && set "PYTHON_EXE=py -3.12"
if not defined PYTHON_EXE (
    py -3.11 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1 && set "PYTHON_EXE=py -3.11"
)
if not defined PYTHON_EXE (
    py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1 && set "PYTHON_EXE=py -3"
)
if not defined PYTHON_EXE (
    for %%P in (
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "C:\Python312\python.exe"
        "C:\Python311\python.exe"
    ) do (
        if exist "%%~P" (
            "%%~P" -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1 && (
                set "PYTHON_EXE=%%~P"
            )
        )
    )
)

if not defined PYTHON_EXE (
    echo ERROR: Python 3.11+ not found. Install from https://www.python.org/downloads/
    pause
    exit /b 1
)
echo Found Python: %PYTHON_EXE%

REM ── Step 2: Create/reuse virtualenv ────────────────────────────────────────
echo [2/8] Setting up virtualenv

if not exist "%VENV_PYTHON%" (
    echo   Creating venv...
    %PYTHON_EXE% -m venv "%VENV_DIR%"
)
echo   Venv ready: !VENV_PYTHON!

REM ── Step 3: Install dependencies ────────────────────────────────────────────
echo [3/8] Installing dependencies...
"%VENV_PYTHON%" -m pip install -r "%PROJECT_DIR%requirements.txt" --quiet --disable-pip-version-check
if errorlevel 1 (
    echo ERROR: pip install failed
    pause
    exit /b 1
)

REM ── Step 4: Auto-configure .env ────────────────────────────────────────────
echo [4/8] Configuring .env
set "DJANGO_SETTINGS_MODULE=config.settings"

if not exist "%ENV_FILE%" (
    echo   Creating .env from .env.example...
    if exist "%ENV_EXAMPLE%" (
        copy "%ENV_EXAMPLE%" "%ENV_FILE%" >nul
        echo   .env created
    ) else (
        (
            echo SECRET_KEY=change-me-to-a-safe-secret-key
            echo DEBUG=True
            echo ALLOWED_HOSTS=*
            echo APOTEK_API_BASE_URL=http://127.0.0.1:8000/api
            echo APOTEK_ADMIN_USERNAME=admin
            echo APOTEK_ADMIN_PASSWORD=admin
            echo DB_ENGINE=django.db.backends.postgresql
            echo DB_NAME=apotek_pos
            echo DB_USER=postgres
            echo DB_PASSWORD=Password09!
            echo DB_HOST=localhost
            echo DB_PORT=5006
        ) > "%ENV_FILE%"
        echo   .env created from defaults
    )
) else (
    echo   .env already exists
)

REM ── Step 5: Auto-detect PostgreSQL port ────────────────────────────────────
echo [5/8] Detecting PostgreSQL port...

set "DETECTED_PORT=none"
for %%P in (5006 5008 5007 5009 5432) do (
    if "!DETECTED_PORT!"=="none" (
        "%VENV_PYTHON%" -c "import psycopg; psycopg.connect(host='localhost', port=%%P, user='postgres', password='Password09!', dbname='postgres', connect_timeout=3); print('found')" 2>nul | findstr /C:"found" >nul 2>&1
        if !errorlevel!==0 (
            set "DETECTED_PORT=%%P"
        )
    )
)

if "!DETECTED_PORT!"=="none" (
    REM Fallback: TCP socket check via Python
    for %%P in (5006 5008 5007 5009 5432) do (
        if "!DETECTED_PORT!"=="none" (
            "%VENV_PYTHON%" -c "import socket; s=socket.socket(); s.settimeout(2); exit(0 if s.connect_ex(('localhost',%%P))==0 else 1)" >nul 2>&1
            if !errorlevel!==0 (
                set "DETECTED_PORT=%%P"
            )
        )
    )
)

if "!DETECTED_PORT!"=="none" (
    echo   WARNING: No PostgreSQL port detected
    echo   SQLite primary will still work; PostgreSQL sync is optional.
    set "DETECTED_PORT="
) else (
    echo   PostgreSQL active on port !DETECTED_PORT!
)

REM ── Step 6: Migrations + DB setup ───────────────────────────────────────────
echo [6/8] Applying migrations...
"%VENV_PYTHON%" "%PROJECT_DIR%manage.py" migrate --run-syncdb
if errorlevel 1 (
    echo ERROR: migrate failed
    pause
    exit /b 1
)

REM Sync .env PG config to ConnectionConfig table if PostgreSQL is available
if defined DETECTED_PORT (
    echo   Syncing DB config to ConnectionConfig table...
    "%VENV_PYTHON%" "%PROJECT_DIR%manage.py" db_sync_config 2>nul
)

REM ── Step 7: First-run setup ────────────────────────────────────────────────
if not exist "%FLAG_FILE%" (
    echo [7/8] First setup: creating admin + seeding...
    "%VENV_PYTHON%" "%PROJECT_DIR%manage.py" shell -c "from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.create_superuser('admin','admin@apotek.local','admin') if not User.objects.filter(username='admin').exists() else print('Admin sudah ada')"
    "%VENV_PYTHON%" "%PROJECT_DIR%manage.py" seed_endpoints 2>nul
    echo. > "%FLAG_FILE%"
) else (
    echo [7/8] DB already initialized.
)

REM ── Step 8: Start server ───────────────────────────────────────────────────
echo [8/8] Starting ApotekMonitor...
echo.
echo ======================================
echo   ApotekMonitor v%VERSION%
echo   http://127.0.0.1:8090
echo   Login: admin / admin
echo ======================================
echo.
"%VENV_PYTHON%" "%PROJECT_DIR%manage.py" runserver 8090
