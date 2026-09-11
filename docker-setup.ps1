<#
.SYNOPSIS
  One-command Docker setup for Laraon on Windows.

  Run from the repository root:
      .\docker-setup.ps1
#>

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

Write-Step "Checking Docker"
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    Write-Host "Docker was not found. Install Docker Desktop from https://www.docker.com/products/docker-desktop/ and re-run this script." -ForegroundColor Red
    exit 1
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker Desktop is not running. Start it and re-run this script." -ForegroundColor Red
    exit 1
}

Write-Step "Building and starting Laraon"
docker compose up --build -d
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose failed to start Laraon."
}

Write-Step "Waiting for Laraon health check"
$healthy = $false
for ($attempt = 1; $attempt -le 30; $attempt++) {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/health" -UseBasicParsing -TimeoutSec 3
        if ($response.StatusCode -eq 200) {
            $healthy = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $healthy) {
    docker compose ps
    throw "Laraon did not become healthy. Check logs with: docker compose logs api ollama-init"
}

Write-Host "`nLaraon is running at http://localhost:8000" -ForegroundColor Green
Write-Host "Open http://localhost:8000/login.html to sign in."
Write-Host "Stop it with: docker compose down"
