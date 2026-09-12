<#
.SYNOPSIS
    Starts Project Aether as a Standalone Desktop Application (App Window Mode).
#>

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "  AETHER - Standalone Desktop Intelligence Application" -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host ""

$PythonExe = Join-Path $ScriptDir ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Write-Host "[ERROR] Virtual environment not found at $PythonExe" -ForegroundColor Red
    Write-Host "Please set up .venv first:" -ForegroundColor Yellow
    Write-Host "  python -m venv .venv" -ForegroundColor Yellow
    Write-Host "  .venv\Scripts\pip install -e ." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit..."
    exit 1
}

function Open-AetherAppWindow {
    param([string]$Url = "http://127.0.0.1:8000")
    $Candidates = @(
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
        "${env:ProgramFiles}\Microsoft\Edge\Application\msedge.exe",
        "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "${env:LocalAppData}\Google\Chrome\Application\chrome.exe"
    )

    foreach ($exe in $Candidates) {
        if ($exe -and (Test-Path $exe)) {
            Start-Process -FilePath $exe -ArgumentList "--app=$Url", "--window-size=1380,900"
            return $true
        }
    }
    Start-Process $Url
    return $false
}

# Check if Ollama is reachable
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
    if ($resp.StatusCode -eq 200) {
        Write-Host "[OK] Local Ollama service is active." -ForegroundColor Green
    }
} catch {
    Write-Host "[!] Local Ollama not detected. Starting in background..." -ForegroundColor Yellow
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

# Ensure port 8000 is clean (clear any stale process from previous crashed runs)
try {
    Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction Stop | ForEach-Object {
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    }
} catch {}


Write-Host "[*] Starting Aether backend service..." -ForegroundColor Cyan
Write-Host "[*] Launching native Desktop App Window..." -ForegroundColor Green
Write-Host "[*] Keep this window open while using Aether. Press Ctrl+C to stop.`n" -ForegroundColor DarkGray

& $PythonExe main.py --portal --open @args

Write-Host "`n=====================================================================" -ForegroundColor Cyan
Write-Host "  Aether desktop application has closed." -ForegroundColor Yellow
Write-Host "=====================================================================" -ForegroundColor Cyan
Start-Sleep -Seconds 1
exit 0

