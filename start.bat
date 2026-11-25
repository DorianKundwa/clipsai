@echo off
REM Starts both halves of ClipsAI:
REM   backend  - the Python pipeline UI (app.py, Gradio)
REM   frontend - the browser studio (web/, SvelteKit)
REM Each runs in its own window; close those windows to stop them.
setlocal

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "BACKEND_PORT=7860"
set "WEB_PORT=5173"
set "PYTHON=%ROOT%\.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
  echo ERROR: no virtual environment found at .venv
  echo Run launch.bat once to create it, then run start.bat again.
  pause
  exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
  echo ERROR: npm was not found. Install Node.js 20+ from https://nodejs.org and re-run.
  pause
  exit /b 1
)

if not exist "%ROOT%\web\node_modules" (
  echo Installing studio dependencies ^(first run^)...
  pushd "%ROOT%\web"
  call npm install
  if errorlevel 1 (
    popd
    echo ERROR: npm install failed.
    pause
    exit /b 1
  )
  popd
)

echo Starting backend on http://127.0.0.1:%BACKEND_PORT%
start "ClipsAI backend" /D "%ROOT%" "%PYTHON%" app.py --port %BACKEND_PORT% --no-browser

echo Starting studio on http://127.0.0.1:%WEB_PORT%
start "ClipsAI studio" /D "%ROOT%\web" cmd /k npm run dev -- --host 127.0.0.1 --port %WEB_PORT%

REM Give Vite a moment to bind the port before opening the page.
timeout /t 5 /nobreak >nul
start "" "http://127.0.0.1:%WEB_PORT%"

echo.
echo Backend:  http://127.0.0.1:%BACKEND_PORT%
echo Studio:   http://127.0.0.1:%WEB_PORT%
echo Close the two windows to stop the servers.
endlocal
