@echo off
setlocal
cd /d "%~dp0"
title Agentic Finance Crew
echo ============================================================
echo    Agentic Finance Crew  -  launcher
echo ============================================================
echo.

REM --- check Python ---
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found on PATH.
  echo Install Python 3.11+ from https://www.python.org/downloads/
  echo ^(tick "Add python.exe to PATH" during install^), then run START again.
  echo.
  pause
  exit /b 1
)

REM --- first-run dependency install (once) ---
if not exist ".setup_done" (
  echo First run: installing dependencies. This takes ~1-2 minutes...
  echo.
  python -m pip install -e ".[dev]"
  if errorlevel 1 (
    echo.
    echo [ERROR] Dependency install failed. Scroll up to see why.
    pause
    exit /b 1
  )
  echo done> .setup_done
  echo.
)

echo ------------------------------------------------------------
echo   Login:   username = admin     password = admin
echo   The app will open in your browser in a few seconds.
echo   KEEP THIS WINDOW OPEN while using the app.
echo   Close this window to stop the server.
echo ------------------------------------------------------------
echo.

REM --- open the browser to the console after the server has a moment to start ---
start "" cmd /c "timeout /t 4 >nul & start "" http://localhost:8000/"

REM --- run the server (this blocks; closing the window stops it) ---
python -m uvicorn app:app --port 8000

pause
