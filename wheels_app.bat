@echo off
setlocal EnableExtensions

REM =================================================
REM  Wheels Manager - Safe Start (no special symbols)
REM  - Creates .venv
REM  - Installs requirements.txt
REM  - Starts wheels_manager.py
REM =================================================

cd /d "%~dp0"

set "APP_FILE=wheels_manager.py"
set "REQ_FILE=requirements.txt"
set "VENV_DIR=.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

REM ---- Check app file ----
if not exist "%APP_FILE%" (
  echo [ERROR] %APP_FILE% not found in: %cd%
  echo         Please place the Python file here.
  pause
  exit /b 1
)

REM ---- Create minimal requirements.txt (no < or >) ----
if not exist "%REQ_FILE%" (
  echo Flask==2.3.3> "%REQ_FILE%"
  echo SQLAlchemy==2.0.29>> "%REQ_FILE%"
  echo [INFO] Created minimal requirements.txt
)

REM ---- Find Python (py.exe preferred, fallback to python.exe) ----
set "PYEXE="
where /q py.exe
if not errorlevel 1 set "PYEXE=py.exe"
if "%PYEXE%"=="" (
  where /q python.exe
  if not errorlevel 1 set "PYEXE=python.exe"
)
if "%PYEXE%"=="" (
  echo [ERROR] Python 3 was not found. Install from python.org.
  pause
  exit /b 1
)
echo [OK] Using %PYEXE%

REM =================================================
REM UPDATE (run updater.py before venv/pip/app)
REM =================================================
if exist "updater.py" (
  echo [INFO] Running updater...
  if /i "%PYEXE%"=="py.exe" (
    "%PYEXE%" -3 "updater.py"
  ) else (
    "%PYEXE%" "updater.py"
  )
  set "UP_RC=%ERRORLEVEL%"
  if "%UP_RC%"=="10" (
    echo [INFO] Code updated. Continuing with environment and start...
  ) else if not "%UP_RC%"=="0" (
    echo [WARN] Updater returned %UP_RC%. Continuing anyway...
  ) else (
    echo [OK] No update needed.
  )
) else (
  echo [INFO] updater.py not found; skipping update check.
)

REM ---- Create venv if missing ----
if not exist "%VENV_PY%" (
  echo [INFO] Creating virtual environment at "%VENV_DIR%" ...
  if /i "%PYEXE%"=="py.exe" (
    "%PYEXE%" -3 -m venv "%VENV_DIR%"
  ) else (
    "%PYEXE%" -m venv "%VENV_DIR%"
  )
  if errorlevel 1 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
  )
)

REM ---- Upgrade pip & install requirements ----
echo [INFO] Upgrading pip ...
"%VENV_PY%" -m pip install --upgrade pip || goto :pip_fail

echo [INFO] Installing requirements ...
"%VENV_PY%" -m pip install -r "%REQ_FILE%" || goto :req_fail

REM ---- Set a default secret if not set ----
if "%WHEELS_SECRET_KEY%"=="" set "WHEELS_SECRET_KEY=BitteAendern-Prod-Secret"

echo [START] Launching app (Ctrl+C to stop) ...
"%VENV_PY%" "%APP_FILE%"
set "EXITCODE=%ERRORLEVEL%"
echo [INFO] App exited with code %EXITCODE%
pause
exit /b %EXITCODE%

:pip_fail
echo [ERROR] pip upgrade failed.
pause
exit /b 1

:req_fail
echo [ERROR] requirements installation failed.
pause
exit /b 1