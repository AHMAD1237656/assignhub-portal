#!/usr/bin/env python3
"""AssignHub: show proctoring inside Quiz > Manage Quiz (UI integration only).

Run from project root (beside manage.py):
  python fix_assignhub_monitoring_inside_quiz.py --check
  python fix_assignhub_monitoring_inside_quiz.py --apply

Safe: no database, migration, grading, timer, MCQ, or quiz lifecycle edits.
"""
from __future__ import annotations

import argparse
import difflib
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

MARKER = '<!-- ASSIGNHUB-QUIZ-MONITORING-UX-V1 -->'


def exactly_once(source: str, needle: str, label: str) -> None:
    if source.count(needle) != 1:
        raise ValueError(f'{label}: expected exactly one anchor, found {source.count(needle)}; refusing unsafe edit.')


def patch_quiz_detail(source: str) -> str:
    if MARKER in source:
        return source
    # Earlier Part 1 installers sometimes added a separate "Exam monitoring" button.
    # Replace that link with integrated controls instead of showing duplicates.
    legacy = ("      <!-- ASSIGNHUB-PROCTORING-PART1 teacher -->\n"
              "      <a class=\"btn btn-outline-primary\" href=\"{% url 'quiz_proctoring:quiz_monitoring' quiz.pk %}\">Exam monitoring</a>\n")
    if legacy in source:
        source = source.replace(legacy, '', 1)
    anchor = '    <div class="ahq-action-bar">'
    exactly_once(source, anchor, 'Quiz manager action bar')
    controls = '''    <div class="ahq-action-bar">
      <!-- ASSIGNHUB-QUIZ-MONITORING-UX-V1 -->
      {% if can_edit %}
      <a class="btn btn-outline-primary" href="{% url 'quiz_proctoring:settings' quiz.pk %}"><i class="bi bi-shield-check" aria-hidden="true"></i> Monitoring settings</a>
      {% else %}
      <a class="btn btn-outline-primary" href="{% url 'quiz_proctoring:quiz_monitoring' quiz.pk %}"><i class="bi bi-shield-check" aria-hidden="true"></i> Monitoring &amp; incidents</a>
      {% endif %}'''
    source = source.replace(anchor, controls, 1)

    # A visible status section on the same Manage Quiz page, not a second dashboard.
    bank_anchor = '    <div class="ahq-card"><div class="ahq-section-bar"><div><h2>Question bank</h2>'
    exactly_once(source, bank_anchor, 'Question bank')
    panel = '''    <section class="ahq-card mb-3" id="ahq-monitoring-settings" aria-labelledby="ahq-monitoring-heading">
      <div class="d-flex align-items-start justify-content-between flex-wrap gap-3">
        <div>
          <span class="ahq-eyebrow">EXAM CONFIGURATION</span>
          <h2 class="ahq-card-title" id="ahq-monitoring-heading">Exam monitoring</h2>
          {% if quiz.proctoring_policy.enabled %}
          <p class="mb-1 text-success"><strong>Monitoring enabled</strong></p>
          <p class="text-muted mb-0">Webcam check: {% if quiz.proctoring_policy.require_camera %}Required{% else %}Optional{% endif %} · Browser events: {% if quiz.proctoring_policy.log_browser_events %}Enabled{% else %}Disabled{% endif %}</p>
          {% else %}
          <p class="mb-0 text-muted">Monitoring is off for this quiz. Students can take it using the normal quiz flow.</p>
          {% endif %}
          {% if not can_edit %}<p class="text-muted mb-0 mt-2">Configuration is locked after publication or when an attempt exists. Previously recorded incidents can still be reviewed.</p>{% endif %}
        </div>
        {% if can_edit %}
        <a class="btn btn-primary" href="{% url 'quiz_proctoring:settings' quiz.pk %}">Configure monitoring</a>
        {% else %}
        <a class="btn btn-outline-primary" href="{% url 'quiz_proctoring:quiz_monitoring' quiz.pk %}">View monitoring records</a>
        {% endif %}
      </div>
    </section>
'''
    return source.replace(bank_anchor, panel + bank_anchor, 1)


def patch_settings_template(source: str) -> str:
    new = source.replace("{% url 'quiz_proctoring:quiz_monitoring' quiz.pk %}",
                         "{% url 'quizzes:detail' quiz.pk %}")
    new = new.replace('← Back to monitoring', '← Back to Manage Quiz')
    new = new.replace('>Cancel</a>', '>Back to Manage Quiz</a>')
    if "{% url 'quizzes:detail' quiz.pk %}" not in new:
        raise ValueError('Monitoring settings template: could not find Quiz link anchor.')
    return new


def patch_settings_redirect(source: str) -> str:
    start = source.find('def settings(request, quiz_pk):')
    if start < 0:
        raise ValueError('Monitoring views: settings() not found.')
    end = source.find('\n@login_required', start + 1)
    if end < 0:
        raise ValueError('Monitoring views: settings() boundary not found.')
    block = source[start:end]
    old = "return redirect('quiz_proctoring:quiz_monitoring', quiz_pk=quiz.pk)"
    new = "return redirect('quizzes:detail', pk=quiz.pk)"
    if old in block:
        exactly_once(block, old, 'Monitoring settings POST redirect')
        block = block.replace(old, new, 1)
    elif new not in block:
        raise ValueError('Monitoring settings redirect was customized; refusing unsafe edit.')
    return source[:start] + block + source[end:]


def patch_monitoring_overview(source: str) -> str:
    # Maintain teacher review screen but point its navigation back to parent Quiz.
    source = source.replace('EXAM MONITORING / STEP 4', 'QUIZ MANAGEMENT / MONITORING')
    source = source.replace('>Quiz details</a>', '>Back to Manage Quiz</a>')
    return source


def patch_sidebar(source: str) -> str:
    # Proctoring retains a separate Django app, not a separate teacher sidebar module.
    legacy = re.compile(
        r'\s*<!-- ASSIGNHUB-PROCTORING-PART1 sidebar -->\s*'
        r'{% if nav_is_teacher or nav_is_admin %}\s*'
        r'<a href="{% url \'quiz_proctoring:classes\' %}"[\s\S]*?'
        r'</a>\s*{% endif %}',
    )
    source = legacy.sub('', source, count=1)
    old = "request.resolver_match.namespace == 'quizzes'"
    new = "request.resolver_match.namespace == 'quizzes' or request.resolver_match.namespace == 'quiz_proctoring'"
    if new not in source:
        exactly_once(source, old, 'Quiz navigation active-state')
        source = source.replace(old, new, 1)
    return source


PATCHES = {
    'templates/quizzes/detail.html': patch_quiz_detail,
    'templates/quiz_proctoring/settings.html': patch_settings_template,
    'quiz_proctoring/views.py': patch_settings_redirect,
    'templates/quiz_proctoring/quiz.html': patch_monitoring_overview,
    'templates/base.html': patch_sidebar,
}


def main() -> None:
    ap = argparse.ArgumentParser(description='Integrate Exam Monitoring into Quiz > Manage Quiz')
    modes = ap.add_mutually_exclusive_group(required=True)
    modes.add_argument('--check', action='store_true', help='Preview only; do not change any files')
    modes.add_argument('--apply', action='store_true', help='Back up and apply scoped UI patches')
    opts = ap.parse_args()
    root = Path(__file__).resolve().parent
    prereqs = ['manage.py', 'quiz_proctoring/models.py', 'quizzes/models.py', 'quiz_proctoring/urls.py']
    missing = [p for p in prereqs + list(PATCHES) if not (root / p).is_file()]
    if missing:
        sys.exit('SAFE ABORT: Missing project files: ' + ', '.join(missing))
    if opts.apply:
        try:
            branch = subprocess.check_output(['git', 'branch', '--show-current'],
                                             cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
            if branch == 'main':
                sys.exit('SAFE ABORT: Current branch is main. Switch to feature/quiz-engine first.')
            print('Git branch:', branch or '(detached)')
        except (OSError, subprocess.CalledProcessError):
            print('WARNING: Could not verify branch; ensure you are on your Quiz feature branch.')

    updated = {}
    try:
        for rel, patcher in PATCHES.items():
            p = root / rel
            old = p.read_text(encoding='utf-8-sig')
            new = patcher(old)
            if rel.endswith('.py'):
                compile(new, rel, 'exec')
            if old != new:
                updated[rel] = (old, new)
            print(('PATCH ' if old != new else 'OK    ') + rel)
    except (ValueError, SyntaxError, UnicodeError) as error:
        sys.exit(f'SAFE ABORT: {error}; no project files were changed.')

    if opts.check:
        for rel, (old, new) in updated.items():
            print(''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                               fromfile=rel, tofile=rel+' (proposed)'))[:5000])
        print(f'Dry run complete; {len(updated)} file(s) would change. No files modified.')
        return
    if not updated:
        print('Already integrated. Nothing modified.')
        return

    backup = root.parent / 'AssignHub_Quiz_Monitoring_UI_Backups' / datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    for rel in updated:
        dst = backup / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, dst)
    try:
        for rel, (_, new) in updated.items():
            (root / rel).write_text(new, encoding='utf-8')
    except Exception as exc:
        for rel in updated:
            shutil.copy2(backup / rel, root / rel)
        sys.exit(f'WRITE ERROR: Original files restored from {backup}: {exc}')
    print(f'Updated {len(updated)} files. Original backups: {backup}')
    print('No migrations required. Restart server and reload browser with Ctrl+F5.')
    print('Open /quizzes/ -> class -> course -> Manage Quiz -> Exam monitoring.')


if __name__ == '__main__':
    main()
