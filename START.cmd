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

REM --- pick a free port (8000, else 8001/8002) in case one is already in use ---
set PORT=8000
netstat -an | findstr ":8000" | findstr /I "LISTENING" >nul && set PORT=8001
netstat -an | findstr ":8001" | findstr /I "LISTENING" >nul && if "%PORT%"=="8001" set PORT=8002

REM --- Local convenience: no login on this machine. Do NOT use in production. ---
set AUTH_DISABLED=1

echo ------------------------------------------------------------
echo   Local mode: NO login required - it opens straight in.
echo   Opening:  http://localhost:%PORT%/
echo   Give it ~5 seconds. If you see 404 or a blank page, just
echo   REFRESH the browser once the server says "Uvicorn running".
echo   KEEP THIS WINDOW OPEN while using the app (close it to stop).
echo ------------------------------------------------------------
echo.

REM --- open the browser AFTER the server has had time to start ---
start "" cmd /c "timeout /t 6 >nul & start "" http://localhost:%PORT%/"

REM --- run the server (this blocks; closing the window stops it) ---
python -m uvicorn app:app --port %PORT%

pause
