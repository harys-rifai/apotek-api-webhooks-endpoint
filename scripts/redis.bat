@echo off
REM redis.bat - Start/stop Redis for ApotekMonitor (Windows)
REM
REM Assumes redis-server.exe is on PATH or in the same scripts directory.
REM Download Redis for Windows: https://redis.io/downloads/

set "REDIS_CONF=%~dp0redis.windows.conf"
set "REDIS_LOG=%TEMP%\redis.log"
set "REDIS_PID=%TEMP%\redis.pid"

if /i "%1"=="start" (
    echo Checking if Redis is already running...
    tasklist /FI "IMAGENAME eq redis-server.exe" /NH | findstr /C:"redis-server" >nul 2>&1
    if not errorlevel 1 (
        echo Redis already running.
        goto :eof
    )
    echo Starting Redis...
    if exist "%REDIS_CONF%" (
        start /B redis-server "%REDIS_CONF%" > "%REDIS_LOG%" 2>&1
    ) else (
        start /B redis-server --port 6379 > "%REDIS_LOG%" 2>&1
    )
    timeout /t 1 >nul
    tasklist /FI "IMAGENAME eq redis-server.exe" /NH | findstr /C:"redis-server" >nul 2>&1
    if not errorlevel 1 (
        echo Redis started on port 6379.
    ) else (
        echo Redis FAILED to start. Check %REDIS_LOG%
    )
    goto :eof
)

if /i "%1"=="stop" (
    echo Stopping Redis...
    taskkill /F /IM redis-server.exe 2>nul
    echo Redis stopped.
    goto :eof
)

if /i "%1"=="status" (
    tasklist /FI "IMAGENAME eq redis-server.exe" /NH | findstr /C:"redis-server" >nul 2>&1
    if not errorlevel 1 (
        echo Redis: RUNNING on port 6379
    ) else (
        echo Redis: STOPPED
    )
    goto :eof
)

if /i "%1"=="restart" (
    %~dp0redis.bat stop
    timeout /t 1 >nul
    %~dp0redis.bat start
    goto :eof
)

echo Usage: %0  ^<start^|stop^|status^|restart^>
exit /b 1
