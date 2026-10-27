
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Project root = parent of scripts folder
$projectRoot = Split-Path -Parent $PSScriptRoot

Set-Location $projectRoot

$python = Join-Path `
    $projectRoot "venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Virtual environment Python not found: $python"
}

function Invoke-Check {
    param(
        [string]$Name,
        [string[]]$CommandArgs
    )

    Write-Host ""
    Write-Host "======================================"
    Write-Host $Name
    Write-Host "======================================"

    & $python @CommandArgs

    if ($LASTEXITCODE -ne 0) {
        throw "FAILED: $Name"
    }

    Write-Host "PASSED: $Name" -ForegroundColor Green
}


# 1. Django configuration
Invoke-Check `
    -Name "Django System Check" `
    -CommandArgs @(
        "manage.py",
        "check"
    )


# 2. Ensure models and migrations match
Invoke-Check `
    -Name "Migration Consistency" `
    -CommandArgs @(
        "manage.py",
        "makemigrations",
        "--check",
        "--dry-run"
    )


# 3. Confirm all migrations are applied
Invoke-Check `
    -Name "Pending Migration Check" `
    -CommandArgs @(
        "manage.py",
        "migrate",
        "--check"
    )


# 4. Accounts
Invoke-Check `
    -Name "Accounts Regression Tests" `
    -CommandArgs @(
        "manage.py",
        "test",
        "accounts",
        "-v",
        "1"
    )


# 5. Assignments
Invoke-Check `
    -Name "Assignments Regression Tests" `
    -CommandArgs @(
        "manage.py",
        "test",
        "assignments",
        "-v",
        "1"
    )


# 6. Departments
Invoke-Check `
    -Name "Departments Regression Tests" `
    -CommandArgs @(
        "manage.py",
        "test",
        "departments",
        "-v",
        "1"
    )


# 7. Semesters + Sections
Invoke-Check `
    -Name "Semesters and Sections Tests" `
    -CommandArgs @(
        "manage.py",
        "test",
        "semesters",
        "-v",
        "1"
    )


# 8. Combined regression test
Invoke-Check `
    -Name "Combined Project Regression" `
    -CommandArgs @(
        "manage.py",
        "test",
        "accounts",
        "assignments",
        "departments",
        "semesters",
        "-v",
        "1"
    )


Write-Host ""
Write-Host "======================================"
Write-Host "ALL PREFLIGHT CHECKS PASSED"
Write-Host "======================================"
Write-Host "Project is ready for browser testing." `
    -ForegroundColor Green
