@echo off
REM ---------------------------------------------------------------------------
REM The Tuesday job. Pulls the week that just finished into data/archive/
REM and writes a log next to this file.
REM
REM Run it by hand any time, or point Task Scheduler at it (see CLAUDE.md).
REM %~dp0 = this file's own folder, so moving the project will not break it.
REM ---------------------------------------------------------------------------
cd /d "%~dp0"

if not exist "logs" mkdir "logs"
for /f "tokens=1-3 delims=/- " %%a in ("%DATE%") do set STAMP=%%c-%%a-%%b

python weekly_update.py %* > "logs\weekly-%STAMP%.log" 2>&1
set RESULT=%ERRORLEVEL%

type "logs\weekly-%STAMP%.log"

if %RESULT% NEQ 0 (
  echo.
  echo Update FAILED with code %RESULT%. The archive was not changed.
  echo Full log: logs\weekly-%STAMP%.log
)

REM Only pause when a person is watching. Task Scheduler passes --scheduled
REM so an unattended run does not sit forever on a keypress that never comes.
echo %* | find "--scheduled" > nul
if errorlevel 1 pause

exit /b %RESULT%
