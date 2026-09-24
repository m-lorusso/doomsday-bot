# Keeps the per-minute IMAX watcher (watch_imax.ps1) running on this PC.
#
# Task Scheduler tries to start it every 5 minutes; if it's already running the
# new start is skipped, so there's only ever one watcher, and if it stops or
# crashes it's back within 5 minutes. It only runs while you're logged in and
# the PC is awake - GitHub Actions remains the backup for when it isn't.
#
# Install:   .\install_local_schedule.ps1
# Check:     Get-ScheduledTask -TaskName DoomsdayImaxWatch | Get-ScheduledTaskInfo
# Log:       Get-Content .\local_watch.log -Tail 20
# Remove:    Unregister-ScheduledTask -TaskName DoomsdayImaxWatch -Confirm:$false

$ErrorActionPreference = "Stop"

$taskName = "DoomsdayImaxWatch"
$script = Join-Path $PSScriptRoot "watch_imax.ps1"
if (-not (Test-Path $script)) { throw "watch_imax.ps1 not found next to this script" }

# The older 15-minute full-check task, if it was ever installed, is superseded.
if (Get-ScheduledTask -TaskName "DoomsdayTicketWatch" -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName "DoomsdayTicketWatch" -Confirm:$false
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`"" `
    -WorkingDirectory $PSScriptRoot

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 7)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "Watches both Sydney IMAX screens for Avengers: Doomsday every minute" -Force | Out-Null

Write-Host "Registered '$taskName'. It starts within a minute and keeps itself running."
Write-Host "Watch it work:  Get-Content .\local_watch.log -Tail 20 -Wait"
