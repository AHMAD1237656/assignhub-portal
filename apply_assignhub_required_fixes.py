#!/usr/bin/env python3
"""AssignHub targeted hardening patch, reviewed against commit 99ad515.

Run inside D:\\assignhub-portal with the project's Python interpreter:
    python apply_assignhub_required_fixes.py --check
    python apply_assignhub_required_fixes.py

The script is idempotent. Existing files are backed up outside the repo.
No model changes, migrations, or automatic grading changes are made.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys

PROJECT = Path(__file__).resolve().parent
EXPECTED = (PROJECT / "manage.py", PROJECT / "accounts" / "forms.py", PROJECT / "assignments" / "similarity.py")


class PatchError(RuntimeError):
    pass


def change_once(source: str, old: str, new: str, label: str) -> str:
    if old == new:
        raise PatchError(f"Invalid patch definition: {label}")
    if new in source:
        return source  # already applied
    occurrences = source.count(old)
    if occurrences != 1:
        raise PatchError(f"{label}: expected one original code anchor, found {occurrences}. File untouched.")
    return source.replace(old, new, 1)


def change_block(source: str, begin: str, end: str, replacement: str, label: str) -> str:
    if replacement in source:
        return source
    if source.count(begin) != 1:
        raise PatchError(f"{label}: begin anchor missing/ambiguous")
    start = source.index(begin)
    stop = source.find(end, start + len(begin))
    if stop == -1:
        raise PatchError(f"{label}: end anchor not found")
    return source[:start] + replacement + source[stop:]


def patch_account_form(s: str) -> str:
    old = '        user = super().save(commit=False)\n\n        user.set_password(self.cleaned_data["password"])'
    new = ('        user = super().save(commit=False)\n\n'
           '        # Role-admin accounts need is_staff for existing permission checks.\n'
           '        # Teacher/Student accounts remain non-staff; never elevate superuser.\n'
           '        user.is_staff = (self.cleaned_data["role"] == UserProfile.Role.ADMIN)\n\n'
           '        user.set_password(self.cleaned_data["password"])')
    return change_once(s, old, new, "accounts/forms.py: staff role")


def patch_dashboard_role(s: str) -> str:
    return change_once(s,
        '    if role == UserProfile.Role.ADMIN:\n        return "admin"',
        '    if role == UserProfile.Role.ADMIN and user.is_staff and user.is_active:\n        return "admin"',
        "config/views.py: dashboard admin authorization")


def patch_submission_list(s: str) -> str:
    begin = '                            {% if is_student_user %}\n'
    end = '                            {% elif submission.status == "GRADED" and submission.marks != None %}'
    replacement = '''                            {% if is_student_user %}
                                {% if submission.status == "GRADED" and submission.marks != None %}
                                    <span class="sl-marks">
                                        {{ submission.marks }}
                                        <small>/ {{ submission.assignment.total_marks }}</small>
                                    </span>
                                {% elif submission.status == "DRAFT" %}
                                    <span class="sl-secondary">—</span>
                                {% else %}
                                    <span class="sl-secondary">Awaiting grading</span>
                                {% endif %}

'''
    s = change_block(s, begin, end, replacement, "submission list: graded marks")
    old = '''                                        <i class="bi bi-file-earmark-arrow-down"></i>
                                        PDF
                                    </a>'''
    new = '''                                        <i class="bi bi-file-earmark-arrow-down"></i>
                                        Download File
                                    </a>'''
    return change_once(s, old, new, "submission list: file label")


def patch_assignment_detail_view(s: str) -> str:
    old = '''    # Assignment deletion is blocked if any
    # submission record exists, including drafts.
    has_any_submissions = (
        assignment.submissions.exists()
    )

    context = {'''
    new = '''    # Assignment deletion is blocked if any
    # submission record exists, including drafts.
    has_any_submissions = (
        assignment.submissions.exists()
    )

    # Keep Edit action consistent with the existing timed-writing edit lock.
    has_timed_attempt = (
        hasattr(assignment, "timed_writing_config")
        and assignment.timed_writing_config.attempts.exists()
    )

    context = {'''
    s = change_once(s, old, new, "assignments/views.py: timed edit flag")
    old_context = '''        "has_final_submissions": has_final_submissions,
        "has_any_submissions": has_any_submissions,'''
    new_context = '''        "has_final_submissions": has_final_submissions,
        "has_any_submissions": has_any_submissions,
        "has_timed_attempt": has_timed_attempt,'''
    return change_once(s, old_context, new_context, "assignments/views.py: template context")


def patch_assignment_detail_template(s: str) -> str:
    return change_once(s,
        '            {% if not has_final_submissions %}\n',
        '            {% if not has_final_submissions and not has_timed_attempt %}\n',
        "assignment detail: Edit visibility")


def patch_similarity(s: str) -> str:
    s = change_once(s, 'from django.core.cache import cache\n',
        'from django.conf import settings\nfrom django.core.cache import cache\n',
        "similarity: configurable import")
    s = change_once(s, 'MAX_COMPARE = 30\n',
        '''# A class of 40+ students must not silently stop at 30 peers.
# Keep a hard ceiling: OCR remains expensive and reports flag truncation.
MAX_COMPARE = max(30, min(int(getattr(settings, "ASSIGNHUB_MAX_COMPARE", 100)), 250))
''', "similarity: candidate cap")
    s = change_once(s,
        '            "Only first 30 comparison "\n            "submissions checked; "',
        '            f"Only first {MAX_COMPARE} comparison "\n            "submissions checked; "',
        "similarity: accurate cap warning")
    return s


def patch_settings(s: str) -> str:
    marker = '# Automatic plagiarism worker (does not run inside web requests).\n'
    extra = '''# Per-submission comparison ceiling. Covers typical 40-student sections;
# hard-clamped to 30..250 inside the similarity engine.
ASSIGNHUB_MAX_COMPARE = int(os.environ.get("ASSIGNHUB_MAX_COMPARE", "100"))

'''
    if extra in s:
        return s
    return change_once(s, marker, extra + marker, "settings: max comparison")


def patch_gitignore(s: str) -> str:
    rules = [
        '.env',
        '.env.*',
        '!.env.example',
        '*.sqlite3.backup',
        '*.before_semesters.backup',
        'AssignHub_Assignments_Redesign_Package/',
        'assignhub_hardening_backup/',
    ]
    lines = set(s.splitlines())
    addition = [rule for rule in rules if rule not in lines]
    if not addition:
        return s
    return s.rstrip('\r\n') + '\n\n# AssignHub security and temporary installer files\n' + '\n'.join(addition) + '\n'


EXPIRY_LOOP = r'''# AssignHub timed-writing expiry worker (local development).
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
'''

WORKER_LOOP = r'''# AssignHub automatic plagiarism worker supervisor (local development).
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
'''

ENV_SAMPLE = '''# Example only. NEVER commit your actual .env file.
DJANGO_SECRET_KEY=REPLACE_WITH_A_NEW_RANDOM_SECRET
DJANGO_DEBUG=True
DJANGO_EMAIL_BACKEND=django.core.mail.backends.filebased.EmailBackend
ASSIGNHUB_PUBLIC_BASE_URL=http://127.0.0.1:8000
ASSIGNHUB_MAX_COMPARE=100
PLAGIARISM_AUTO_SEMANTIC=False
'''

ACCOUNTS_TEST = '''"""Targeted tests for Account/Admin permission consistency."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.forms import UserCreateForm
from accounts.models import UserProfile
from config.views import get_dashboard_role


class RequiredHardeningAccountTests(TestCase):
    def test_new_role_admin_is_staff_and_not_superuser(self):
        form = UserCreateForm(data={
            "username": "patch_role_admin",
            "first_name": "Admin", "last_name": "Tester",
            "email": "patch_admin@example.com",
            "password": "NewAdminPass123!", "role": UserProfile.Role.ADMIN,
            "is_active": True,
        })
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(get_dashboard_role(user), "admin")

    def test_new_teacher_is_not_staff(self):
        form = UserCreateForm(data={
            "username": "patch_teacher", "first_name": "Teacher",
            "last_name": "Tester", "email": "patch_teacher@example.com",
            "password": "NewTeacherPass123!", "role": UserProfile.Role.TEACHER,
            "is_active": True,
        })
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertFalse(user.is_staff)
        self.assertEqual(get_dashboard_role(user), "teacher")

    def test_nonstaff_role_admin_does_not_get_admin_dashboard(self):
        user = get_user_model().objects.create_user(
            username="legacy_unprivileged_admin", password="ValidPass123!"
        )
        UserProfile.objects.create(user=user, role=UserProfile.Role.ADMIN)
        self.assertEqual(get_dashboard_role(user), "unknown")
'''

ASSIGNMENTS_TEST = '''"""Regression checks for the targeted AssignHub display fixes."""
from decimal import Decimal

from django.urls import reverse

from .models import Submission
from .tests import AssignmentTestBase


class RequiredHardeningAssignmentTests(AssignmentTestBase):
    def test_student_sees_graded_marks_in_submission_directory(self):
        self.make_submission(
            student=self.student, status=Submission.Status.GRADED,
            marks=Decimal("73.00"),
        )
        self.login_as(self.student)
        response = self.client.get(reverse("assignments:submissions"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "73.00")
        self.assertNotContains(response, "Pending release")

    def test_detail_does_not_offer_edit_after_timed_attempt(self):
        from timed_writing.models import TimedWritingConfig, TimedWritingAttempt

        cfg = TimedWritingConfig.objects.create(
            assignment=self.assignment, is_enabled=True,
            duration_minutes=15,
        )
        draft = self.make_submission(
            student=self.student, status=Submission.Status.DRAFT,
        )
        TimedWritingAttempt.objects.create(
            config=cfg, student=self.student, submission=draft,
        )
        self.login_as(self.teacher)
        response = self.client.get(reverse("assignments:detail", args=[self.assignment.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response, 'href="' + reverse("assignments:edit", args=[self.assignment.pk]) + '"'
        )
'''


PATCHES = {
    "accounts/forms.py": patch_account_form,
    "config/views.py": patch_dashboard_role,
    "templates/assignments/submission_list.html": patch_submission_list,
    "assignments/views.py": patch_assignment_detail_view,
    "templates/assignments/assignment_detail.html": patch_assignment_detail_template,
    "assignments/similarity.py": patch_similarity,
    "config/settings.py": patch_settings,
    ".gitignore": patch_gitignore,
}

NEW_FILES = {
    "scripts/run_timed_expiry_loop.ps1": EXPIRY_LOOP,
    "scripts/run_plagiarism_worker_supervised.ps1": WORKER_LOOP,
    "accounts/test_required_fixes.py": ACCOUNTS_TEST,
    "assignments/test_required_fixes.py": ASSIGNMENTS_TEST,
    ".env.example": ENV_SAMPLE,
}

SENSITIVE_TRACKED = (
    ".env",
    "db.sqlite3.backup",
    "db.sqlite3.before_semesters.backup",
    "AssignHub_Assignments_Redesign_Package",
)


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=PROJECT, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=check,
    )


def git_is_repository() -> bool:
    try:
        return run_git("rev-parse", "--is-inside-work-tree").stdout.strip() == "true"
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def tracked_sensitive_items() -> list[str]:
    if not git_is_repository():
        return []
    result = run_git("ls-files", "-z", "--", *SENSITIVE_TRACKED)
    tracked = [p for p in result.stdout.split("\0") if p]
    return tracked


def rotate_secret_key(old_env: str) -> str:
    # Regex only touches the single DJANGO_SECRET_KEY setting.
    pattern = re.compile(r'^DJANGO_SECRET_KEY\s*=\s*.*$', flags=re.MULTILINE)
    if len(pattern.findall(old_env)) != 1:
        raise PatchError("Local .env must contain exactly one DJANGO_SECRET_KEY setting")
    key = secrets.token_urlsafe(64)
    return pattern.sub('DJANGO_SECRET_KEY="' + key + '"', old_env, count=1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Preflight, do not change files")
    parser.add_argument(
        "--no-rotate-key", action="store_true",
        help="Keep local key unchanged (NOT SAFE if key was exposed in public Git history)",
    )
    parser.add_argument("--no-git", action="store_true", help="Do not untrack sensitive files from Git")
    args = parser.parse_args()

    if not all(path.is_file() for path in EXPECTED):
        raise PatchError("Put this script in your AssignHub project ROOT, beside manage.py")
    pending: dict[Path, str] = {}
    for relative, transform in PATCHES.items():
        path = PROJECT / relative
        if not path.is_file():
            raise PatchError(f"Required file missing: {relative}")
        original = path.read_text(encoding="utf-8-sig")
        revised = transform(original)
        if revised != original:
            pending[path] = revised

    for relative, content in NEW_FILES.items():
        path = PROJECT / relative
        if path.is_file():
            # Do not overwrite existing user content even if there is an older version.
            if path.read_text(encoding="utf-8-sig") != content:
                print(f"SKIPPED existing custom file: {relative}")
        elif not path.exists():
            pending[path] = content
        else:
            raise PatchError(f"Expected file but directory exists at {relative}")

    env_path = PROJECT / ".env"
    if not args.no_rotate_key:
        if not env_path.is_file():
            raise PatchError("Local .env file missing. Create it, or use --no-rotate-key for source-only patch")
        old_env = env_path.read_text(encoding="utf-8-sig")
        new_env = rotate_secret_key(old_env)
        pending[env_path] = new_env

    # Verify syntax for ALL future Python source before writing a single file.
    for path, content in pending.items():
        if path.suffix == ".py":
            compile(content, str(path), "exec")

    git_items = [] if args.no_git else tracked_sensitive_items()
    print(f"PROJECT: {PROJECT}")
    print("Patch validated against current source anchors; no model/migration changes.")
    for path in pending:
        label = path.relative_to(PROJECT).as_posix()
        if label == ".env":
            print("ROTATE: .env / DJANGO_SECRET_KEY (value never displayed)")
        else:
            print("UPDATE: " + label)
    for item in git_items:
        print("GIT UNTRACK (local copy preserved): " + item)
    if args.check:
        print("PREFLIGHT PASSED — no files changed.")
        return 0

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backups = PROJECT.parent / "AssignHub_Hardening_Backups" / timestamp
    backups.mkdir(parents=True, exist_ok=True)
    try:
        for path in pending:
            if path.exists():
                relative = path.relative_to(PROJECT)
                target = backups / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
        for path, content in pending.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
        if git_items:
            result = run_git("rm", "--cached", "--", *git_items, check=False)
            if result.returncode != 0:
                print("WARNING: Git untracking failed; correct manually:", result.stderr.strip())
            else:
                print("Git index cleaned; sensitive files remain on disk.")
    except Exception:
        for path in pending:
            candidate = backups / path.relative_to(PROJECT)
            if candidate.is_file():
                shutil.copy2(candidate, path)
            elif path.is_file() and path.relative_to(PROJECT).as_posix() in NEW_FILES:
                path.unlink()
        raise
    print("\nApplied. Backup directory:", backups)
    print("NEXT: restart server; existing logins + pending activation links may need renewal.")
    print("NEXT: python manage.py check")
    print("NEXT: python manage.py test accounts.test_required_fixes assignments.test_required_fixes")
    print("NEXT: python manage.py test accounts assignments timed_writing student_onboarding")
    print("Optional local workers (separate PowerShell terminals):")
    print("  powershell -ExecutionPolicy Bypass -File scripts/run_plagiarism_worker_supervised.ps1")
    print("  powershell -ExecutionPolicy Bypass -File scripts/run_timed_expiry_loop.ps1")
    print("SECURITY: old Git history still contains tracked secrets/DB snapshots; review history cleanup.")
    print("REVIEW: git status ; git diff ; git diff --cached")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PatchError as exc:
        print("PATCH ABORTED: " + str(exc), file=sys.stderr)
        raise SystemExit(2)
