# AssignHub automatic plagiarism worker supervisor (local development).
# Run in its own PowerShell terminal. If the Django worker crashes, restart.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = Join-Path $root "venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
Write-Host "Plagiarism worker supervisor running."
while ($true) {
    & $python (Join-Path $root "manage.py") run_plagiarism_worker
    Write-Warning "Worker exited; retrying after 5 seconds. Close this window to stop."
    Start-Sleep -Seconds 5
}
