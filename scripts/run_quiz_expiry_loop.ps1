# Optional development helper; Ctrl+C to stop. Production: schedule every minute.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
while ($true) {
    python manage.py finalize_quiz_attempts
    Start-Sleep -Seconds 60
}
