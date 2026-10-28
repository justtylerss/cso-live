@echo off
rem Pull the latest CSO Live, then restart the watcher so it runs the new code.
cd /d "%~dp0"
git pull || (pause & exit /b 1)
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8765 -State Listen -EA SilentlyContinue | %% { Stop-Process -Id $_.OwningProcess -Force }"
.venv\Scripts\python -m pip install -q -r requirements.txt
echo Updated. Run start.bat.
pause
