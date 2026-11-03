#!/usr/bin/env python3
"""Repair missing AssignHub Part 1 live monitoring panel hook (no migrations).
Usage: python fix_proctoring_live_panel.py --check|--apply
"""
import argparse
import difflib
import shutil
import sys
from datetime import datetime
from pathlib import Path


def patch_views(text):
    imports = 'from quiz_proctoring.models import MonitoringSession, ProctoringPolicy'
    if imports not in text:
        anchor = 'from .services import begin, finish, refresh, save_choice, student_can_see\n'
        if text.count(anchor) != 1:
            raise ValueError('Cannot safely locate quiz service imports; nothing changed.')
        text = text.replace(anchor, anchor + imports + '\n', 1)
    start = text.find('def take(request, pk):')
    end = text.find('\n@login_required', start + 1)
    if start < 0 or end < 0:
        raise ValueError('Cannot safely locate take() view boundaries.')
    block = text[start:end]
    if "'proctoring_enabled':" not in block:
        anchor = "        'server_epoch': int(timezone.now().timestamp()),"
        if block.count(anchor) != 1:
            raise ValueError('Unexpected take() context. Nothing changed.')
        addition = ("\n        'proctoring_enabled': ProctoringPolicy.objects.filter(quiz=quiz, enabled=True).exists() and MonitoringSession.objects.filter(attempt=attempt).exists(),"
                    "\n        'camera_required': ProctoringPolicy.objects.filter(quiz=quiz, enabled=True, require_camera=True).exists(),"
                    "\n        'browser_logging': ProctoringPolicy.objects.filter(quiz=quiz, enabled=True, log_browser_events=True).exists(),")
        block = block.replace(anchor, anchor + addition, 1)
    else:
        for key in ('camera_required', 'browser_logging'):
            if f"'{key}':" not in block:
                raise ValueError(f'Incomplete/custom {key} context. Refusing unsafe change.')
    return text[:start] + block + text[end:]


def patch_template(text):
    if "{% include 'quiz_proctoring/_live_panel.html' %}" in text:
        return text
    anchor = '  <div class="alert alert-warning" id="ahq-status"'
    if text.count(anchor) != 1:
        raise ValueError('Cannot safely locate quiz status panel in take.html.')
    return text.replace(anchor,
        "  <!-- ASSIGNHUB-PROCTORING-PART1 live -->\n"
        "  {% if proctoring_enabled %}{% include 'quiz_proctoring/_live_panel.html' %}{% endif %}\n" + anchor, 1)


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    paths = [root / 'quizzes/views.py', root / 'templates/quizzes/take.html']
    prerequisites = [root / 'manage.py', root / 'quiz_proctoring/models.py', root / 'templates/quiz_proctoring/_live_panel.html', root / 'static/js/quiz_proctoring_live.js']
    missing = [str(p.relative_to(root)) for p in prerequisites + paths if not p.is_file()]
    if missing:
        sys.exit('Missing required project files: ' + ', '.join(missing))
    before = [p.read_text(encoding='utf-8') for p in paths]
    try:
        after = [patch_views(before[0]), patch_template(before[1])]
        compile(after[0], str(paths[0]), 'exec')
    except (ValueError, SyntaxError) as exc:
        sys.exit('SAFE ABORT: ' + str(exc))
    changes = [(p, old, new) for p, old, new in zip(paths, before, after) if old != new]
    for p in paths:
        print(('CHANGE' if any(q == p for q, _, _ in changes) else 'OK') + ': ' + str(p.relative_to(root)))
    if args.check:
        for p, old, new in changes:
            print(''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile=str(p.name), tofile=str(p.name) + '.fixed')))
        return
    if not changes:
        print('Already correct. No files modified.')
        return
    directory = root / 'quiz_proctoring_patch_backups' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    directory.mkdir(parents=True, exist_ok=False)
    for p, old, new in changes:
        target = directory / p.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
    for p, old, new in changes:
        p.write_text(new, encoding='utf-8')
    print(f'Applied {len(changes)} targeted file patches. Backups: {directory}')


if __name__ == '__main__':
    main()
