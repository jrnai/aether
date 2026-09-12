# Project Aether - Register Daily Morning Briefing Scheduled Task
param(
    [string]$Time = "07:30",
    [switch]$Uninstall
)

$TaskName = "AetherMorningBriefing"

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "[OK] Unregistered '$TaskName' from Windows Task Scheduler." -ForegroundColor Green
    exit 0
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$BatPath = Join-Path $ProjectDir "scripts\launch_briefing.bat"

if (-not (Test-Path $BatPath)) {
    Write-Error "Could not find launch_briefing.bat at: $BatPath"
    exit 1
}

# 1. Action: execute launch_briefing.bat
$Action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"`"$BatPath`"`"" `
    -WorkingDirectory $ProjectDir

# 2. Trigger: Daily at specified time (e.g. 7:30 AM)
$ParsedTime = [datetime]::ParseExact($Time, "HH:mm", [System.Globalization.CultureInfo]::InvariantCulture)
$Trigger = New-ScheduledTaskTrigger -Daily -At $ParsedTime

# 3. Settings:
# - StartWhenAvailable: Run task as soon as possible after a scheduled start is missed
# - AllowStartIfOnBatteries: Run even if laptop is on battery power
# - DontStopIfGoingOnBatteries: Continue running if power source changes
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

# 4. Register Scheduled Task
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Project Aether autonomous once-per-day Morning Briefing with missed schedule catchup." `
    -Force

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "  [OK] Successfully registered scheduled task '$TaskName'" -ForegroundColor Green
Write-Host "  Scheduled Time : Every day at $Time" -ForegroundColor White
Write-Host "  Missed Catch-Up: Enabled (Runs as soon as PC powers on or wakes)" -ForegroundColor White
Write-Host "  Target Script  : $BatPath" -ForegroundColor White
Write-Host "==================================================================" -ForegroundColor Cyan
