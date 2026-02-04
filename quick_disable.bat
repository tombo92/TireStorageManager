@echo off
setlocal
REM === Disable/Enable positions helper ===
cd /d %~dp0

if not exist .venv\Scripts\activate.bat (
  echo [setup] Creating virtual environment...
  py -3 -m venv .venv || python -m venv .venv
)
call .venv\Scripts\activate.bat

REM Ensure repo root is importable
set PYTHONPATH=%CD%

REM Forward all args to the tool
python tools\quick_disable.py %*
endlocal
