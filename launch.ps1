<#
.SYNOPSIS
    One-click launcher for ClipsAI Studio (the Gradio web UI).

.DESCRIPTION
    Uses (or creates) the project virtual environment (./.venv), ensures the ClipsAI
    package and its UI dependencies are installed, then starts the ClipsAI Studio web
    app in your browser.

    The installer only runs when something is missing, so an already working
    environment is never re-resolved.

.EXAMPLE
    .\launch.ps1
    .\launch.ps1 -Port 8000
    .\launch.ps1 -Port 8000 -Auth "user:password"
    .\launch.ps1 -Reinstall
#>
[CmdletBinding()]
param(
    [int]$Port = 7860,
    [switch]$Share,
    [switch]$NoBrowser,
    [switch]$Reinstall,
    [string]$Auth = "",
    [string]$MaxFileSize = ""
)

$ErrorActionPreference = "Stop"

$Root   = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Venv   = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"

function Write-Step { param([string]$Message) Write-Host "`n==> $Message" -ForegroundColor Cyan }

function Test-Module {
    param([string]$Name)
    & $Python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$Name') else 1)" 2>$null
    return ($LASTEXITCODE -eq 0)
}

if ($Reinstall -and (Test-Path $Venv)) {
    Write-Step "Removing existing virtual environment"
    Remove-Item -Recurse -Force $Venv
}

# --------------------------------------------------------------------------- #
# 1. Virtual environment
# --------------------------------------------------------------------------- #
if (-not (Test-Path $Python)) {
    Write-Step "Creating virtual environment (.venv)"
    $ok = $false
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try { & py -3.9 -m venv $Venv; $ok = (Test-Path $Python) } catch { }
        if (-not $ok) { try { & py -3 -m venv $Venv; $ok = (Test-Path $Python) } catch { } }
    }
    if (-not $ok -and (Get-Command python -ErrorAction SilentlyContinue)) {
        try { & python -m venv $Venv; $ok = (Test-Path $Python) } catch { }
    }
    if (-not (Test-Path $Python)) {
        Write-Host "ERROR: could not create a virtual environment." -ForegroundColor Red
        Write-Host "Install Python 3.9+ from https://www.python.org/downloads/ and re-run." -ForegroundColor Red
        exit 1
    }
}

# --------------------------------------------------------------------------- #
# 2. Dependencies (only install what is missing)
# --------------------------------------------------------------------------- #
if ($Reinstall -or -not (Test-Module "clipsai")) {
    Write-Step "Installing ClipsAI and its dependencies (first run; this can take a while)"
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -e ".[ui]"

    # Compatibility pins required by ClipsAI's ML stack.
    & $Python -m pip install "setuptools<81" "mediapipe==0.10.14"
    if ($env:OS -eq "Windows_NT") { & $Python -m pip install python-magic-bin }
    if (-not (Test-Module "whisperx")) { & $Python -m pip install "whisperx==3.3.1" }

    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: dependency installation failed." -ForegroundColor Red
        exit 1
    }
    Write-Host "Setup complete." -ForegroundColor Green
} elseif (-not (Test-Module "gradio")) {
    Write-Step "Installing UI dependency (gradio)"
    & $Python -m pip install "gradio>=4.44,<5"
}

# --------------------------------------------------------------------------- #
# 3. Launch
# --------------------------------------------------------------------------- #
$appArgs = @("app.py", "--port", "$Port")
if ($Share)       { $appArgs += "--share" }
if ($NoBrowser)   { $appArgs += "--no-browser" }
if ($Auth)        { $appArgs += @("--auth", $Auth) }
if ($MaxFileSize) { $appArgs += @("--max-file-size", $MaxFileSize) }

Write-Step "Starting ClipsAI Studio at http://127.0.0.1:$Port"
Write-Host "Press Ctrl+C to stop the server." -ForegroundColor DarkGray

& $Python @appArgs
