# Run separately from the Django server. Ctrl+C stops.
# Reminder events are deduplicated by the database; an hourly schedule is safe.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
while ($true) {
    python manage.py send_deadline_notifications
    Start-Sleep -Seconds 3600
}
