@echo off
setlocal enabledelayedexpansion

REM pg_failover.bat — Unified PostgreSQL switchover / failover / repair script
REM
REM Detects primary & standby across ports 5006/5008, then offers:
REM   [1] Status   — show role (primary/standby) + replication health
REM   [2] Failover  — promote standby -> new primary, stop old primary
REM   [3] Rebuild   — pg_basebackup new standby from current primary
REM   [4] Repair    — full cycle: failover + rebuild old primary
REM   [5] Swing DB  — update .env DB_PORT to point at the new primary
REM   [0] Exit
REM

set "PGHOME=C:\Program Files\PostgreSQL\18"
set "PSQL=%PGHOME%\bin\psql.exe"
set "PG_BASEBACKUP=%PGHOME%\bin\pg_basebackup.exe"
set "PG_CTL=%PGHOME%\bin\pg_ctl.exe"

set "PRIMARY_PORT=5006"
set "STANDBY_PORT=5008"
set "REPLICA_USER=replicator"
set "REPL_PASSWORD=Password09!"
set "PG_USER=postgres"
set "PG_PASSWORD=Password09!"
set "DATA_DIR_5006=C:\PostgreSQL\data5006"
set "DATA_DIR_5008=C:\PostgreSQL\data5008"
set "SVC_5006=postgresql-x64-18-5006"
set "SVC_5008=postgresql-x64-18-5008"
set "SCRIPT_DIR=%~dp0"
set "ENV_FILE=%SCRIPT_DIR%\..\.env"
if not exist "%ENV_FILE%" set "ENV_FILE=%SCRIPT_DIR%\..\..\ApotekApps\.env"
set "PGPASSWORD=%PG_PASSWORD%"

call :menu
goto :eof

:menu
cls
echo.
echo === PostgreSQL Switchover / Failover ===
echo.
echo   1) Show status (primary + standby)
echo   2) Failover (promote %STANDBY_PORT%, stop %PRIMARY_PORT%)
echo   3) Rebuild standby from primary
echo   4) Repair (full cycle: failover + rebuild)
echo   5) Swing DB port (.env + table)
echo   0) Exit
echo.
set /p choice="Choose [0-5]: "
echo.
if "%choice%"=="1" ( call :check_status & pause )
if "%choice%"=="2" ( call :failover & pause )
if "%choice%"=="3" ( call :rebuild_standby & pause )
if "%choice%"=="4" ( call :repair & pause )
if "%choice%"=="5" ( call :swing_db_port & pause )
if "%choice%"=="0" ( echo Bye. & exit /b 0 )
goto :menu

:check_status
echo ===== PRIMARY (port %PRIMARY_PORT%) =====
call :check_role %PRIMARY_PORT% role1
if "!role1!"=="primary" (
    echo   Role: PRIMARY
        "%PSQL%" -h 127.0.0.1 -p %PRIMARY_PORT% -U %PG_USER% -c "SELECT client_addr, state, sync_state FROM pg_stat_replication;" 2>nul
) else if "!role1!"=="standby" (
    echo   Role: STANDBY ^(unexpected for primary^)
) else (
    echo   Role: OFFLINE
)
echo.
echo ===== STANDBY (port %STANDBY_PORT%) =====
call :check_role %STANDBY_PORT% role2
if "!role2!"=="standby" (
    echo   Role: STANDBY
        "%PSQL%" -h 127.0.0.1 -p %STANDBY_PORT% -U %PG_USER% -c "SELECT status, conninfo FROM pg_stat_wal_receiver;" 2>nul
) else if "!role2!"=="primary" (
    echo   Role: PRIMARY ^(unexpected for standby^)
) else (
    echo   Role: OFFLINE
)
echo.
exit /b 0

:check_role
set port=%1
set retvar=%2
set result=
"%PSQL%" -h 127.0.0.1 -p %port% -U %PG_USER% -tA -c "SELECT pg_is_in_recovery();" 2>nul | findstr /R "t f" >nul 2>&1
if errorlevel 1 (
    set %retvar%=offline
) else (
        for /f "delims=" %%i in ('"%PSQL%" -h 127.0.0.1 -p %port% -U %PG_USER% -tA -c "SELECT pg_is_in_recovery();" 2^>nul') do (
        set result=%%i
    )
    if "!result!"=="t" (
        set %retvar%=standby
    ) else if "!result!"=="f" (
        set %retvar%=primary
    ) else (
        set %retvar%=offline
    )
)
exit /b 0

:failover
echo ===== FAILOVER: promote standby -> new primary =====
call :check_role %STANDBY_PORT% srole
if not "!srole!"=="standby" (
    echo ERROR: Port %STANDBY_PORT% is not standby ^(role=!srole!^). Aborting.
    exit /b 1
)

echo Step 1 - Promote standby on %STANDBY_PORT%...
"%PG_CTL%" -D "%DATA_DIR_5008%" promote
if errorlevel 1 (
    echo Promote FAILED
    exit /b 1
)
echo   Waiting for promotion...
timeout /t 10 >nul

echo Step 2 - Stop old primary on %PRIMARY_PORT%...
sc stop %SVC_5006% 2>nul

echo.
echo Switchover completed.
echo   %STANDBY_PORT% is now PRIMARY
echo   %PRIMARY_PORT% is stopped (needs rebuild)
echo.
call :swing_db_port
exit /b 0

:rebuild_standby
echo ===== REBUILD STANDBY from primary =====
call :check_role %PRIMARY_PORT% prole
if not "!prole!"=="primary" (
    echo ERROR: Port %PRIMARY_PORT% is not primary ^(role=!prole!^).
    echo   Promote a standby first, or run Repair.
    exit /b 1
)

echo Step 1 - Stop standby on %STANDBY_PORT%...
sc stop %SVC_5008% 2>nul
timeout /t 2 >nul

echo Step 2 - Wipe old standby data...
if exist "%DATA_DIR_5008%" rmdir /s /q "%DATA_DIR_5008%"
mkdir "%DATA_DIR_5008%"

echo Step 3 - pg_basebackup from primary (%PRIMARY_PORT%)...
"%PG_BASEBACKUP%" -h 127.0.0.1 -p %PRIMARY_PORT% -U %REPLICA_USER% -D "%DATA_DIR_5008%" -R -X stream -P
if errorlevel 1 (
    echo pg_basebackup FAILED
    exit /b 1
)

echo Step 4 - Configure recovery...
>>"%DATA_DIR_5008%\postgresql.auto.conf" echo port = %STANDBY_PORT%
>>"%DATA_DIR_5008%\postgresql.auto.conf" echo hot_standby = on

echo Step 5 - Start standby...
sc start %SVC_5008% 2>nul

echo Standby rebuilt on %STANDBY_PORT%.
exit /b 0

:repair
echo ===== FULL REPAIR: failover + rebuild =====
call :failover
echo.
call :rebuild_standby
echo.
call :check_status
exit /b 0

:swing_db_port
echo ===== Swinging DB port to new primary (%STANDBY_PORT%) =====
if not exist "%ENV_FILE%" type nul > "%ENV_FILE%"

REM Check if DB_PORT exists in .env
set "HAS_PORT=0"
for /f "delims=" %%L in ('type "%ENV_FILE%"') do (
    echo %%L | findstr /B /C:"DB_PORT=" >nul
    if not errorlevel 1 set "HAS_PORT=1"
)

set "UPDATED=0"
if exist "%TEMP%\.env_tmp" del "%TEMP%\.env_tmp"
for /f "tokens=1 delims=" %%L in ('type "%ENV_FILE%"') do (
    echo %%L | findstr /B /C:"DB_PORT=" >nul
    if not errorlevel 1 (
        echo DB_PORT=%STANDBY_PORT%>> "%TEMP%\.env_tmp"
        set "UPDATED=1"
    ) else (
        echo %%L>> "%TEMP%\.env_tmp"
    )
)
move /Y "%TEMP%\.env_tmp" "%ENV_FILE%" >nul 2>&1
if "%UPDATED%"=="0" echo DB_PORT=%STANDBY_PORT%>> "%ENV_FILE%"

echo   Updated .env: DB_PORT=%STANDBY_PORT%

REM Sync to ConnectionConfig table
if exist "%SCRIPT_DIR%\..\venv\Scripts\python.exe" (
    cd /d "%SCRIPT_DIR%\.."
    "%SCRIPT_DIR%\..\venv\Scripts\python.exe" manage.py db_sync_config 2>nul
) else if exist "%SCRIPT_DIR%\..\venv\Scripts\python.exe" (
    cd /d "%SCRIPT_DIR%\.."
    "%SCRIPT_DIR%\..\venv\Scripts\python.exe" manage.py db_sync_config 2>nul
)
exit /b 0
