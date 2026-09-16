# Create Aether Desktop App Shortcut on User's Home Screen / Desktop
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$AssetsDir = Join-Path $ProjectRoot "assets"
if (-not (Test-Path $AssetsDir)) {
    New-Item -ItemType Directory -Path $AssetsDir -Force | Out-Null
}

$IconPath = Join-Path $AssetsDir "aether.ico"
$AssetsLogo = Join-Path $AssetsDir "logo.jpg"
$WebLogo = Join-Path "$ProjectRoot\src\web\static" "logo.jpg"
$FallbackImage = "C:\Users\jrrya\.gemini\antigravity\brain\8954aea9-d488-4cc1-a87e-229871c276a4\aether_app_logo_1789434116383.jpg"

# 1. Ensure logo.jpg is synchronized
if ((-not (Test-Path $AssetsLogo)) -and (Test-Path $FallbackImage)) {
    Copy-Item $FallbackImage $AssetsLogo -Force
}
if ((Test-Path $AssetsLogo) -and (-not (Test-Path $WebLogo))) {
    Copy-Item $AssetsLogo $WebLogo -Force
}

# 2. Generate multi-resolution .ico if missing
if ((-not (Test-Path $IconPath)) -and (Test-Path $AssetsLogo)) {
    $VenvPy = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path $VenvPy) {
        & $VenvPy -c "from PIL import Image; img = Image.open(r'$AssetsLogo').convert('RGBA'); img.save(r'$IconPath', format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])"
        Write-Host "[OK] Generated multi-resolution ICO via Pillow: $IconPath" -ForegroundColor Green
    } else {
        try {
            Add-Type -AssemblyName System.Drawing
            $img = [System.Drawing.Bitmap]::FromFile($AssetsLogo)
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
