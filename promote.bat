@echo off

set PGHOME=C:\Program Files\PostgreSQL\18

echo Promote PostgreSQL 5008 to PRIMARY ...

"%PGHOME%\bin\pg_ctl.exe" ^
-D "C:\PostgreSQL\data5008" ^
promote

timeout /t 5 >nul

"%PGHOME%\bin\psql.exe" ^
-h 127.0.0.1 ^
-p 5008 ^
-U postgres ^
-c "SELECT pg_is_in_recovery();"

pause
