@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv" (
  python -m venv .venv
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\pip.exe" install -r requirements.txt

if not exist "logs" (
  mkdir logs
)

schtasks /Create /SC DAILY /ST 08:30 /TN "SEO Feishu Data Sync" /TR "%~dp0run_daily.bat" /F

echo.
echo Install finished.
echo Please copy .env.example to .env and fill API credentials.
echo.
pause

endlocal
