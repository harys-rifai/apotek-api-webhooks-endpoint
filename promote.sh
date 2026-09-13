@echo off

set PGHOME=C:\Program Files\PostgreSQL\18

echo Step 1 - Promote 5008 ...

"%PGHOME%\bin\pg_ctl.exe" ^
-D "C:\PostgreSQL\data5008" ^
promote

timeout /t 10

echo Step 2 - Stop old primary 5006 ...

sc stop postgresql-x64-18-5006

echo.
echo Switchover completed.
echo 5008 is now PRIMARY.

pause
