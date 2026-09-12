# Create Aether Desktop App Shortcut on User's Home Screen / Desktop
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$AssetsDir = Join-Path $ProjectRoot "assets"
if (-not (Test-Path $AssetsDir)) {
    New-Item -ItemType Directory -Path $AssetsDir -Force | Out-Null
}

$IconPath = Join-Path $AssetsDir "aether.ico"
$SourceImage = "C:\Users\jrrya\.gemini\antigravity-ide\brain\f6586a8a-0cbd-4e62-b95e-1d93ea2a028c\aether_app_icon_1788631602687.jpg"

# 1. Generate high-resolution .ico from the generated logo if it doesn't exist
if (Test-Path $SourceImage) {
    Copy-Item $SourceImage (Join-Path $AssetsDir "logo.jpg") -Force
    Copy-Item $SourceImage (Join-Path "$ProjectRoot\src\web\static" "logo.jpg") -Force

    try {
        Add-Type -AssemblyName System.Drawing
        $img = [System.Drawing.Bitmap]::FromFile($SourceImage)
        $resized = New-Object System.Drawing.Bitmap 256, 256
        $g = [System.Drawing.Graphics]::FromImage($resized)
        $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $g.DrawImage($img, 0, 0, 256, 256)
        $g.Dispose()

        $hIcon = $resized.GetHicon()
        $icon = [System.Drawing.Icon]::FromHandle($hIcon)
        $fs = New-Object System.IO.FileStream $IconPath, ([System.IO.FileMode]::Create)
        $icon.Save($fs)
        $fs.Close()
        $icon.Dispose()
        $resized.Dispose()
        $img.Dispose()
        Write-Host "[OK] Created icon at: $IconPath" -ForegroundColor Green
    } catch {
        Write-Warning "Could not convert image to ICO: $_"
    }
}

# 2. Resolve target directories
$Destinations = @()

$SpecialDesktop = [Environment]::GetFolderPath([Environment+SpecialFolder]::Desktop)
if ($SpecialDesktop -and (Test-Path $SpecialDesktop)) { $Destinations += $SpecialDesktop }

$LocalDesktop = Join-Path $env:USERPROFILE "Desktop"
if ($LocalDesktop -and (Test-Path $LocalDesktop) -and ($Destinations -notcontains $LocalDesktop)) { $Destinations += $LocalDesktop }

$StartMenu = [Environment]::GetFolderPath([Environment+SpecialFolder]::Programs)
if ($StartMenu -and (Test-Path $StartMenu) -and ($Destinations -notcontains $StartMenu)) { $Destinations += $StartMenu }

$TargetBat = Join-Path $ProjectRoot "start_portal.bat"
$WshShell = New-Object -ComObject WScript.Shell

Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "  Installing Aether App Shortcuts" -ForegroundColor Green
Write-Host "=====================================================================" -ForegroundColor Cyan

foreach ($dir in $Destinations) {
    $lnkPath = Join-Path $dir "Aether.lnk"
    $Shortcut = $WshShell.CreateShortcut($lnkPath)
    $Shortcut.TargetPath = $TargetBat
    $Shortcut.WorkingDirectory = $ProjectRoot
    $Shortcut.Description = "Aether - Desktop Intelligence Dashboard"
    if (Test-Path $IconPath) {
        $Shortcut.IconLocation = "$IconPath,0"
    }
    $Shortcut.WindowStyle = 7  # 7 = Minimized (starts minimized to taskbar while browser opens in focus)
    $Shortcut.Save()
    Write-Host "[OK] Created: $lnkPath" -ForegroundColor Green
}

Write-Host "Target: $TargetBat" -ForegroundColor Yellow
Write-Host "Icon:   $IconPath" -ForegroundColor Yellow
Write-Host ""
