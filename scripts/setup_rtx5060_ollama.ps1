# ==============================================================================
# Project Aether - NVIDIA RTX 5060 & Ollama Optimization Setup Script
# Configures Flash Attention, KV cache quantization, and verifies 16k models
# ==============================================================================

Write-Host "`n=======================================================" -ForegroundColor Cyan
Write-Host " Project Aether - RTX 5060 (8GB VRAM) Ollama Optimizer" -ForegroundColor Cyan
Write-Host "=======================================================`n" -ForegroundColor Cyan

# 1. Enable Flash Attention in Windows User Environment
$currentFlash = [Environment]::GetEnvironmentVariable("OLLAMA_FLASH_ATTENTION", "User")
if ($currentFlash -ne "1") {
    Write-Host "[*] Setting OLLAMA_FLASH_ATTENTION = 1 in Windows User Environment..." -ForegroundColor Yellow
    [Environment]::SetEnvironmentVariable("OLLAMA_FLASH_ATTENTION", "1", "User")
    $env:OLLAMA_FLASH_ATTENTION = "1"
    Write-Host "[OK] Flash Attention enabled! (Reduces 16k context VRAM footprint by ~50%)" -ForegroundColor Green
    $needsOllamaRestart = $true
} else {
    Write-Host "[OK] OLLAMA_FLASH_ATTENTION is already enabled (1)" -ForegroundColor Green
}

# 2. Configure KV Cache Type (q8_0) for Optimal 8 GB VRAM balance
$currentKV = [Environment]::GetEnvironmentVariable("OLLAMA_KV_CACHE_TYPE", "User")
if ($currentKV -ne "q8_0") {
    Write-Host "[*] Setting OLLAMA_KV_CACHE_TYPE = q8_0 in Windows User Environment..." -ForegroundColor Yellow
    [Environment]::SetEnvironmentVariable("OLLAMA_KV_CACHE_TYPE", "q8_0", "User")
    $env:OLLAMA_KV_CACHE_TYPE = "q8_0"
    Write-Host "[OK] KV Cache quantization set to q8_0!" -ForegroundColor Green
    $needsOllamaRestart = $true
} else {
    Write-Host "[OK] OLLAMA_KV_CACHE_TYPE is already set to q8_0" -ForegroundColor Green
}

# 3. Verify Ollama Daemon Connectivity
Write-Host "`n[*] Checking connection to local Ollama daemon at http://127.0.0.1:11434..." -ForegroundColor Yellow
try {
    $res = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -Method Get -TimeoutSec 5
    $installed = $res.models | ForEach-Object { $_.name }
    Write-Host "[OK] Ollama is online. Installed models:" -ForegroundColor Green
    foreach ($m in $installed) {
        Write-Host "     - $m" -ForegroundColor Gray
    }
} catch {
    Write-Host "[!] Warning: Cannot reach Ollama at http://127.0.0.1:11434. Please ensure Ollama is running." -ForegroundColor Red
    $installed = @()
}

# 4. Check Specialized Task Models
Write-Host "`n[*] Auditing Specialized Model Setup for Aether:" -ForegroundColor Yellow

# Coding model
if ($installed -contains "qwen2.5-coder:7b") {
    Write-Host "  [OK] Coding Model: qwen2.5-coder:7b is installed" -ForegroundColor Green
} else {
    Write-Host "  [MISSING] Coding Model: Run 'ollama pull qwen2.5-coder:7b'" -ForegroundColor Yellow
}

# General / Agentic model
if ($installed -contains "qwen2.5:7b-instruct") {
    Write-Host "  [OK] Agentic & Chat Model: qwen2.5:7b-instruct is installed" -ForegroundColor Green
} else {
    Write-Host "  [MISSING] Agentic Model: Run 'ollama pull qwen2.5:7b-instruct'" -ForegroundColor Yellow
}

# Reasoning model
if ($installed -contains "deepseek-r1:7b") {
    Write-Host "  [OK] Reasoning Model: deepseek-r1:7b is installed" -ForegroundColor Green
} else {
    Write-Host "  [RECOMMENDED] Reasoning Model: deepseek-r1:7b not yet installed." -ForegroundColor Yellow
    Write-Host "                To install, run: ollama pull deepseek-r1:7b" -ForegroundColor Cyan
}

if ($needsOllamaRestart) {
    Write-Host "`n[IMPORTANT] Environment variables were updated. Please quit and restart Ollama from your system tray or terminal so the GPU optimizations take effect!`n" -ForegroundColor Magenta
} else {
    Write-Host "`n[SUCCESS] Your RTX 5060 environment is fully tuned for Project Aether!`n" -ForegroundColor Green
}
