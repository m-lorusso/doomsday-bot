# Optional: run the bot from this PC every 15 minutes via Task Scheduler,
# instead of (or as a backup to) GitHub Actions. Only fires while the machine
# is on, which is why GitHub Actions is the better primary.
#
# Install:   .\install_local_schedule.ps1
# Remove:    Unregister-ScheduledTask -TaskName "DoomsdayTicketWatch" -Confirm:$false

$ErrorActionPreference = "Stop"

$taskName = "DoomsdayTicketWatch"
$script = Join-Path $PSScriptRoot "run_once.ps1"

if (-not (Test-Path $script)) { throw "run_once.ps1 not found next to this script" }

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`""

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 15)

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "Checks Event Cinemas for Avengers: Doomsday tickets" -Force | Out-Null

Write-Host "Registered scheduled task '$taskName' (every 15 minutes)."
Write-Host "Run it now with: Start-ScheduledTask -TaskName $taskName"
