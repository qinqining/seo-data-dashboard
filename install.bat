@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv" (
  python -m venv .venv
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\pip.exe" install -r requirements.txt

if not exist "logs" mkdir logs
if not exist "reports" mkdir reports

rem Remove legacy daily scheduled task if install.bat was run before.
schtasks /Delete /TN "SEO Feishu Data Sync" /F >nul 2>&1

echo.
echo Install finished.
echo Please copy .env.example to .env and fill API credentials.
echo Run sync manually: double-click run_sync.bat (about once per week).
echo.
pause

endlocal
