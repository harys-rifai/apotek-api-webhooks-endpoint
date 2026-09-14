@echo off
REM Example script that demonstrates input fields and argument passing
REM
REM Script Arguments:
REM %1 - name: Enter your name
REM %2 - message: Enter a greeting message

echo ==========================================
echo Hello, %~1!
echo Message: %~2
echo ==========================================
echo.
echo This is an example script button that:
echo - Takes user inputs (name and message)
echo - Passes them as positional arguments (%~1, %~2)
echo - Runs in workspace context using ^<workspace^>

echo Script executed successfully at: %date% %time%
