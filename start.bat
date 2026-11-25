@echo off
REM Starts the unified ClipsAI Studio (FastAPI backend + SvelteKit frontend on one port).
setlocal

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "PORT=7860"
set "PYTHON=%ROOT%\.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
  echo ERROR: no virtual environment found at .venv
  echo Run launch.bat once to create it, then run start.bat again.
  pause
  exit /b 1
)

if not exist "%ROOT%\web\build\client\index.html" (
  where npm >nul 2>nul
  if errorlevel 1 (
    echo ERROR: web/build/client/index.html is missing and npm was not found.
    pause
    exit /b 1
  )
  pushd "%ROOT%\web"
  if not exist "node_modules" (
    echo Installing frontend dependencies...
    call npm install
    if errorlevel 1 (
      popd
      pause
      exit /b 1
    )
  )
  echo Building unified frontend...
  call npm run build
  if errorlevel 1 (
    popd
    pause
    exit /b 1
  )
  popd
)

echo Starting unified ClipsAI Studio on http://127.0.0.1:%PORT%
"%PYTHON%" app.py --port %PORT%
endlocal
