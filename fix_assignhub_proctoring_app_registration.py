#!/usr/bin/env python3
"""Repair only missing quiz_proctoring INSTALLED_APPS and URL registration.

Use in the AssignHub folder containing manage.py:
  python fix_assignhub_proctoring_app_registration.py --check
  python fix_assignhub_proctoring_app_registration.py --apply

Safe: checks for existing entries, backs up changed files, does not touch models,
quiz logic, migrations, data or notification logic.
"""
import argparse
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = 'quiz_proctoring'
APP_CONFIG = 'quiz_proctoring.apps.QuizProctoringConfig'


def settings_patch(source):
    installed = re.search(r'(?m)^\s*INSTALLED_APPS\s*=', source)
    if not installed:
        raise ValueError('Cannot find INSTALLED_APPS in config/settings.py')
    # Already registered, either with class-path or Django package-path.
    if re.search(r'''["']quiz_proctoring(?:\.apps\.QuizProctoringConfig)?["']''', source):
        return source, 'already present'
    anchor = re.search(r'''(?m)^(?P<indent>\s*)(?P<q>["'])quizzes(?:\.apps\.QuizzesConfig)?(?P=q)\s*,[^\n]*\n''', source)
    if not anchor:
        raise ValueError('Quiz app registration line not found; settings.py unchanged')
    insert = f'{anchor.group("indent")}"{APP_CONFIG}",\n'
    return source[:anchor.end()] + insert + source[anchor.end():], 'add missing INSTALLED_APPS entry'


def urls_patch(source):
    if re.search(r'''include\s*\(\s*["']quiz_proctoring\.urls["']\s*\)''', source):
        return source, 'already present'
    if not re.search(r'\bfrom\s+django\.urls\s+import\s+.*\binclude\b', source):
        raise ValueError('config/urls.py does not import include; inspect manually')
    anchor = re.search(r'''(?m)^(?P<indent>\s*)path\s*\(\s*["']quizzes/["']\s*,\s*include\s*\(\s*["']quizzes\.urls["']\s*\)\s*\)\s*,[^\n]*\n''', source)
    if not anchor:
        raise ValueError('Quiz URL registration line not found; urls.py unchanged')
    insert = f'{anchor.group("indent")}path("proctoring/", include("quiz_proctoring.urls")),\n'
    return source[:anchor.end()] + insert + source[anchor.end():], 'add missing /proctoring/ URL'


def main():
    parser = argparse.ArgumentParser(description='Repair AssignHub Proctoring app and URLs only')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true', help='Preview without changes')
    group.add_argument('--apply', action='store_true', help='Back up and fix missing registrations')
    args = parser.parse_args()

    expected = [ROOT / 'manage.py', ROOT / 'quiz_proctoring' / 'models.py', ROOT / 'quiz_proctoring' / 'apps.py', ROOT / 'quiz_proctoring' / 'tests.py']
    missing = [str(f.relative_to(ROOT)) for f in expected if not f.is_file()]
    if missing:
        raise SystemExit('Required file(s) missing: ' + ', '.join(missing) + '. No changes made.')
    if not re.search(r'(?m)^class\s+QuizProctoringConfig\s*\(', (ROOT / 'quiz_proctoring' / 'apps.py').read_text(encoding='utf-8-sig')):
        raise SystemExit('Unexpected quiz_proctoring/apps.py. No changes made.')
    targets = [
        (ROOT / 'config' / 'settings.py', settings_patch),
        (ROOT / 'config' / 'urls.py', urls_patch),
    ]
    updated = {}
    for path, transform in targets:
        original = path.read_text(encoding='utf-8-sig')
        try:
            result, reason = transform(original)
        except ValueError as exc:
            raise SystemExit(f'Cannot safely patch {path.relative_to(ROOT)}: {exc}. No changes made.')
        action = 'CHANGE' if result != original else 'OK'
        print(f'{action:7s} {path.relative_to(ROOT)} — {reason}')
        if result != original:
            updated[path] = (original, result)
    if args.check:
        print('Check only. No files changed. Use --apply to repair.')
        return
    if not updated:
        print('Both app and URLs are already registered. Inspect active Django settings:')
        print('python manage.py shell -c "from django.conf import settings; print(settings.SETTINGS_MODULE); print(settings.INSTALLED_APPS)"')
        return
    backup_dir = ROOT.parent / 'AssignHub_Proctoring_Registration_Backups' / datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    try:
        for path in updated:
            backup = backup_dir / path.relative_to(ROOT)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
        for path, (_, new) in updated.items():
            path.write_text(new, encoding='utf-8')
    except Exception as exc:
        for path, (original, _) in updated.items():
            path.write_text(original, encoding='utf-8')
        raise SystemExit(f'Patch failed and original file contents restored: {exc}')
    print('Repair applied. Backups:', backup_dir)
    print('Next: python manage.py check')
    print('      python manage.py migrate quiz_proctoring')
    print('      python manage.py test quiz_proctoring quizzes notifications')

if __name__ == '__main__':
    main()
