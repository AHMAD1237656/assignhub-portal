# AssignHub timed-writing expiry worker (local development).
# Run in a separate PowerShell terminal while testing timed assignments.
# Ctrl+C stops the loop. The app's existing finalizer is unmodified.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = Join-Path $root "venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
Write-Host "Timed-writing expiry checker running (60-second interval)."
while ($true) {
    & $python (Join-Path $root "manage.py") finalized_timed_attempts
    if ($LASTEXITCODE -ne 0) { Write-Warning "Expiry check failed; next attempt in 60 seconds." }
    Start-Sleep -Seconds 60
}
