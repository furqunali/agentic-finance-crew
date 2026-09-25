@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Sync Agentic Finance Crew to GitHub
echo ============================================================
echo    Sync your work + tests to GitHub
echo ============================================================
echo.

REM --- must be a git clone connected to GitHub ---
git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 (
  echo [ERROR] This folder is not connected to GitHub yet.
  echo Ask to run the one-time setup that links it to the repo.
  echo.
  pause
  exit /b 1
)

REM --- run the tests locally first ---
echo Running tests locally...
python -m pytest -q
if errorlevel 1 (
  echo.
  echo [!] Tests FAILED. You can still push ^(GitHub will show the failure^),
  echo     but it's better to fix first. Close this window to cancel,
  echo     or press a key to push anyway.
  pause
)
echo.

REM --- anything to sync? ---
git add -A
git diff --cached --quiet
if not errorlevel 1 (
  echo Nothing new to sync - everything is already on GitHub.
  echo.
  pause
  exit /b 0
)

set "MSG="
set /p MSG=Describe your change (Enter for a default):
if "!MSG!"=="" set "MSG=local update"

git commit -m "!MSG!"
echo.
echo Pushing to GitHub...
git push
if errorlevel 1 (
  echo.
  echo [ERROR] Push failed. If it asks to sign in to GitHub, do that once and retry.
  pause
  exit /b 1
)

echo.
echo ------------------------------------------------------------
echo   Done. GitHub Actions will now run the full test suite and
echo   update the green/red badge in ~1-2 minutes. Watch it here:
echo   https://github.com/furqunali/agentic-finance-crew/actions
echo ------------------------------------------------------------
echo.
pause
