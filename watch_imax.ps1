# Per-minute IMAX watcher for this PC.
#
# GitHub's scheduler only gets round to this repo every few hours, which is far
# too slow for IMAX. This runs the IMAX-only watcher from here instead: both
# IMAX screens every minute, plus answering /check and /imax in Telegram.
#
#   .\watch_imax.ps1          watch for 6 hours, then exit
#   .\watch_imax.ps1 30       watch for 30 minutes
#
# install_local_schedule.ps1 restarts it automatically, so in normal use you
# never run this by hand. Output goes to local_watch.log next to this file.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$envFile = Join-Path $PSScriptRoot ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $name, $value = $line.Split("=", 2)
            Set-Item -Path "Env:$($name.Trim())" -Value $value.Trim()
        }
    }
}

# Its own state, so it never fights GitHub's copy in git. Seeded from GitHub's
# on first run so it starts knowing what's already been announced.
$env:STATE_FILE = Join-Path $PSScriptRoot "local_state.json"
if (-not (Test-Path $env:STATE_FILE) -and (Test-Path "state.json")) {
    Copy-Item "state.json" $env:STATE_FILE
}

# GitHub sends the daily report; this watcher only speaks up for IMAX or when asked.
$env:HEARTBEAT_HOURS = "0"

$env:LOG_FILE = Join-Path $PSScriptRoot "local_watch.log"
if ((Test-Path $env:LOG_FILE) -and (Get-Item $env:LOG_FILE).Length -gt 2MB) {
    Move-Item $env:LOG_FILE "$($env:LOG_FILE).old" -Force
}

$minutes = if ($args.Count -gt 0) { [int]$args[0] } else { 360 }
python -m bot.main --imax-only --imax-watch ($minutes * 60)
exit $LASTEXITCODE
