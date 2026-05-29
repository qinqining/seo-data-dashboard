@echo off
setlocal

cd /d "%~dp0"

echo SEO data sync started. This may take a few minutes...
echo.

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" sync.py
) else (
  python sync.py
)

echo.
if errorlevel 1 (
  echo Sync failed. Check the latest file in logs\
) else (
  echo Sync finished.
)
echo.
pause

endlocal
