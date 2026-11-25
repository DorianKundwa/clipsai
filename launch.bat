@echo off
REM One-click launcher for ClipsAI Studio (Windows).
REM Double-click this file, or run:  launch.bat [-Port 8000] [-Share] [-Reinstall]
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch.ps1" %*
if errorlevel 1 (
  echo.
  echo Something went wrong. See the messages above.
  pause
)
endlocal
