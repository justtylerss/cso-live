@echo off
rem One-time setup: a private Python env in .venv, the packages, then the self-check.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% -c "import sys,struct; assert sys.version_info>=(3,11) and struct.calcsize('P')==8" 2>nul || (
  echo Needs 64-bit Python 3.11 or newer: https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^)
  pause & exit /b 1
)
if not exist .venv %PY% -m venv .venv
.venv\Scripts\python -m pip install -q --upgrade pip
.venv\Scripts\python -m pip install -q -r requirements.txt || (echo pip install failed & pause & exit /b 1)
echo Running the self-check (about a minute)...
.venv\Scripts\python -I edge_research\cso\cso_live.py --test
pause
