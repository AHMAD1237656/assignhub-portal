"""Repair AssignHub Part 1 preflight gate without modifying quiz scoring or migrations.

Usage: python fix_proctoring_preflight_gate.py --check|--apply
"""
from __future__ import annotations
import argparse
import difflib
from datetime import datetime
from pathlib import Path
import shutil
import sys

START = 'def start(request, pk):'
END = '\n@login_required\n@never_cache\n@require_GET\ndef take(request, pk):'
OLD = '    attempt = begin(pk, request.user)'
GATE = "    if is_proctored(quiz) and not QuizAttempt.objects.filter(quiz=quiz, student=request.user).exists():\n        return redirect('quiz_proctoring:device_check', quiz_pk=quiz.pk)\n"
IMPORT = 'from quiz_proctoring.services import is_proctored'


def change(src: str) -> tuple[str, str]:
    if START not in src or END not in src:
        raise RuntimeError('Could not locate expected Quiz start/take views. No files changed.')
    lo = src.index(START)
    hi = src.index(END, lo)
    block = src[lo:hi]
    if block.count(OLD) != 1:
        raise RuntimeError('Unexpected quiz start implementation. No files changed.')
    changed = False
    if IMPORT not in src:
        # Detect existing import with trailing comment, but no risk of duplicate.
        src = src.replace('from .services import begin, finish, refresh, save_choice, student_can_see\n',
                          'from .services import begin, finish, refresh, save_choice, student_can_see\n'
                          + IMPORT + '\n', 1)
        if IMPORT not in src:
            raise RuntimeError('Missing expected quiz imports. No files changed.')
        changed = True
    lo = src.index(START)
    hi = src.index(END, lo)
    block = src[lo:hi]
    if GATE not in block:
        # Fail closed rather than silently replace an unknown conditional.
        if 'is_proctored(quiz)' in block:
            raise RuntimeError('Custom/partial preflight gate found. Please review manually; no files changed.')
        block = block.replace(OLD, GATE + OLD, 1)
        src = src[:lo] + block + src[hi:]
        changed = True
    return src, ('PATCH REQUIRED' if changed else 'ALREADY CORRECT')


def main():
    p = argparse.ArgumentParser()
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--apply', action='store_true')
    args = p.parse_args()
    root = Path(__file__).resolve().parent
    if not (root / 'manage.py').exists():
        sys.exit('ERROR: Run from the Django project root alongside manage.py')
    file = root / 'quizzes' / 'views.py'
    if not file.is_file():
        sys.exit('ERROR: quizzes/views.py does not exist')
    original = file.read_text(encoding='utf-8')
    try:
        updated, status = change(original)
    except RuntimeError as exc:
        sys.exit('ERROR: ' + str(exc))
    print(status + ': quizzes/views.py')
    if args.check and updated != original:
        print(''.join(difflib.unified_diff(original.splitlines(True), updated.splitlines(True),
                                        fromfile='before', tofile='after')))
    if args.apply and updated != original:
        compile(updated, str(file), 'exec')
        backup = root / 'quiz_proctoring_patch_backups' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        backup.mkdir(parents=True)
        shutil.copy2(file, backup / 'views.py')
        file.write_text(updated, encoding='utf-8')
        print(f'Patched. Original backup: {backup / "views.py"}')
    elif args.apply:
        print('No changes needed.')


if __name__ == '__main__':
    main()
