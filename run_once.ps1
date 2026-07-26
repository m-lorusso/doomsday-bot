# Runs one check locally. Loads .env if present, then passes any extra args
# straight through, e.g.:
#   .\run_once.ps1 --dry-run
#   .\run_once.ps1 --test-alert

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

python -m bot.main @args
exit $LASTEXITCODE
