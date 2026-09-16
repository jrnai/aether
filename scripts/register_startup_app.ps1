# Register Project Aether to Auto-Start silently on Windows login (Zero terminal/console window)
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$VbsLauncher = Join-Path $ProjectRoot "scripts\launch_app_silent.vbs"
$IconPath = Join-Path $ProjectRoot "assets\aether.ico"

if (-not (Test-Path $VbsLauncher)) {
    Write-Error "Launcher not found at: $VbsLauncher"
    exit 1
}

$StartupDir = [Environment]::GetFolderPath([Environment+SpecialFolder]::Startup)
$ShortcutPath = Join-Path $StartupDir "Aether.lnk"

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "wscript.exe"
$Shortcut.Arguments = "`"$VbsLauncher`""
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.Description = "Project Aether - Desktop Intelligence Application"
if (Test-Path $IconPath) {
    $Shortcut.IconLocation = "$IconPath,0"
}
$Shortcut.WindowStyle = 7  # Minimized/hidden
$Shortcut.Save()

Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "  Project Aether Auto-Startup Installed" -ForegroundColor Green
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "Startup Shortcut : $ShortcutPath" -ForegroundColor Yellow
Write-Host "Silent Launcher  : $VbsLauncher" -ForegroundColor Yellow
Write-Host "Icon             : $IconPath" -ForegroundColor Yellow
Write-Host ""
Write-Host "Aether will now automatically launch in native desktop app mode without any terminal on system boot." -ForegroundColor Green
