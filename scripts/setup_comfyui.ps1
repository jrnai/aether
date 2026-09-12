<#
.SYNOPSIS
    Automated ComfyUI and SDXL-Turbo setup script for Project Aether on Windows.
.DESCRIPTION
    Checks for NVIDIA GPU (RTX 5060), sets up ComfyUI, and downloads high-speed
    SDXL-Turbo / SDXL-Lightning weights for real-time 1024x1024 local image generation.
#>

param(
    [string]$InstallDir = "$HOME\ComfyUI",
    [switch]$DownloadLightning,
    [switch]$SkipModelDownload
)

$ErrorActionPreference = "Stop"

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "   Project Aether - Local ComfyUI + SDXL Setup        " -ForegroundColor White
Write-Host "=======================================================" -ForegroundColor Cyan

# 1. GPU Check
Write-Host "[1/4] Checking NVIDIA GPU acceleration..." -ForegroundColor Yellow
$gpu = Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match "NVIDIA|GeForce|RTX" } | Select-Object -First 1
if ($gpu) {
    Write-Host "      Detected GPU: $($gpu.Name)" -ForegroundColor Green
} else {
    Write-Host "      Warning: No NVIDIA GPU detected. ComfyUI will run on CPU (slower)." -ForegroundColor DarkYellow
}

# 2. Check or Clone ComfyUI
Write-Host "`n[2/4] Setting up ComfyUI repository at: $InstallDir" -ForegroundColor Yellow
if (-not (Test-Path $InstallDir)) {
    Write-Host "      Cloning ComfyUI from official repository..." -ForegroundColor Gray
    git clone https://github.com/comfyanonymous/ComfyUI.git $InstallDir
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to clone ComfyUI repository. Please ensure git is installed."
    }
} else {
    Write-Host "      ComfyUI directory already exists. Pulling latest updates..." -ForegroundColor Gray
    Push-Location $InstallDir
    git pull --quiet
    Pop-Location
}

# 3. Python Environment & PyTorch with CUDA
Write-Host "`n[3/4] Checking Python & PyTorch CUDA environment..." -ForegroundColor Yellow
$venvPython = "$PSScriptRoot\..\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    $venvPython = "python"
}

Write-Host "      Ensuring PyTorch with NVIDIA CUDA 13.0 (RTX 50-series Blackwell / sm_120) is installed..." -ForegroundColor Gray
& $venvPython -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu130

Write-Host "      Installing/verifying ComfyUI requirements..." -ForegroundColor Gray
& $venvPython -m pip install -r "$InstallDir\requirements.txt"

# 4. Checkpoint Model Download
$ckptDir = "$InstallDir\models\checkpoints"
New-Item -ItemType Directory -Force -Path $ckptDir | Out-Null

if (-not $SkipModelDownload) {
    Write-Host "`n[4/4] Checking SDXL diffusion models..." -ForegroundColor Yellow

    if ($DownloadLightning) {
        $modelName = "sdxl_lightning_4step.safetensors"
        $modelUrl = "https://huggingface.co/ByteDance/SDXL-Lightning/resolve/main/sdxl_lightning_4step.safetensors"
    } else {
        $modelName = "sd_xl_turbo_1.0_fp16.safetensors"
        $modelUrl = "https://huggingface.co/stabilityai/sdxl-turbo/resolve/main/sd_xl_turbo_1.0_fp16.safetensors"
    }

    $targetPath = Join-Path $ckptDir $modelName
    if (Test-Path $targetPath) {
        Write-Host "      Found model checkpoint: $modelName" -ForegroundColor Green
    } else {
        Write-Host "      Downloading $modelName (~6.5GB) from Hugging Face..." -ForegroundColor Cyan
        Write-Host "      Destination: $targetPath" -ForegroundColor Gray
        Write-Host "      (This may take several minutes depending on your internet connection)" -ForegroundColor Gray
        
        try {
            Start-BitsTransfer -Source $modelUrl -Destination $targetPath -DisplayName "Downloading $modelName"
            Write-Host "      Download completed successfully!" -ForegroundColor Green
        } catch {
            Write-Host "      BitsTransfer unavailable, falling back to curl..." -ForegroundColor Yellow
            curl.exe -L -o $targetPath $modelUrl
        }
    }
}

Write-Host "`n=======================================================" -ForegroundColor Cyan
Write-Host "   ComfyUI Setup Complete!                             " -ForegroundColor Green
Write-Host "   To start the local image generation server:         " -ForegroundColor White
Write-Host "   Run: scripts\run_comfyui.bat                        " -ForegroundColor Yellow
Write-Host "=======================================================" -ForegroundColor Cyan
