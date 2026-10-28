@echo off
rem Daily: TradingView in debug mode, the CSO watcher in the background, the page in your browser.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File launch_tv.ps1
powershell -NoProfile -Command "try{(iwr http://127.0.0.1:8765/ping -UseBasicParsing -TimeoutSec 1)|Out-Null;exit 0}catch{exit 1}" || (
  start "" .venv\Scripts\pythonw -I edge_research\cso\cso_live.py --serve
  echo Starting the watcher (loads the history, ~10 s^)...
  timeout /t 10 /nobreak >nul
)
start "" http://127.0.0.1:8765/
