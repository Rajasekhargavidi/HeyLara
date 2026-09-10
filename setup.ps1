<#
.SYNOPSIS
  One-command setup for Laraon on a new Windows machine — no Docker needed.

  Run this after cloning the repo:
      git clone https://github.com/Rajasekhargavidi/HeyLara.git jarvis
      cd jarvis
      .\setup.ps1

  It creates a virtual environment, installs Python dependencies, pulls the
  required Ollama models, creates .env from .env.example if missing, and
  starts the server. Safe to re-run — every step is a no-op if already done.

.NOTES
  Prerequisites this script does NOT install for you (one-time, per machine):
    - Python 3.11+        https://www.python.org/downloads/
    - Ollama               https://ollama.com/download
  Both are normal installers, not blocked by the same policies that can
  block Docker Desktop's WSL2/Hyper-V requirement on managed laptops.
#>

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

# --- 1. Check prerequisites ---
Write-Step "Checking prerequisites"

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "Python was not found on PATH. Install it from https://www.python.org/downloads/ and re-run this script." -ForegroundColor Red
    exit 1
}
Write-Host "Found: $(python --version)"

$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
    Write-Host "Ollama was not found on PATH. Install it from https://ollama.com/download and re-run this script." -ForegroundColor Red
    exit 1
}
Write-Host "Found: ollama"

# --- 2. Virtual environment ---
Write-Step "Setting up Python virtual environment (.venv)"
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
$venvPython = ".\.venv\Scripts\python.exe"

# --- 3. Install dependencies ---
Write-Step "Installing Python dependencies"
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -r apps\api\requirements.txt

# --- 4. .env ---
Write-Step "Checking .env"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host ".env created from .env.example. Edit it to add real API keys (Groq, LinkedIn, etc.) if you have them — the app runs fine with none of them set, using local Ollama and mock/demo providers." -ForegroundColor Yellow
} else {
    Write-Host ".env already exists — leaving it as-is."
}

# --- 5. Ollama models ---
Write-Step "Checking Ollama is running"
$ollamaUp = $false
try {
    Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 3 | Out-Null
    $ollamaUp = $true
} catch {
    Write-Host "Ollama doesn't seem to be running yet. Starting it in the background..." -ForegroundColor Yellow
    Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

Write-Step "Pulling required Ollama models (skips instantly if already pulled)"
ollama pull llama3.2:3b
ollama pull nomic-embed-text

# --- 6. Done ---
Write-Step "Setup complete"
Write-Host "Starting Laraon at http://localhost:8000 ..." -ForegroundColor Green
Write-Host "Press Ctrl+C to stop.`n"
& $venvPython -m uvicorn apps.api.main:app --port 8000
