# Remove Project Aether from Windows Startup folder
$ErrorActionPreference = "Stop"

$StartupDir = [Environment]::GetFolderPath([Environment+SpecialFolder]::Startup)
$ShortcutPath = Join-Path $StartupDir "Aether.lnk"

if (Test-Path $ShortcutPath) {
    Remove-Item $ShortcutPath -Force
    Write-Host "[OK] Removed Aether from Windows startup: $ShortcutPath" -ForegroundColor Green
} else {
    Write-Host "Aether was not present in the Windows startup folder." -ForegroundColor Yellow
}
