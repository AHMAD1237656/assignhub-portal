#!/usr/bin/env python3
"""Targeted AssignHub quiz submit UX and in-app quiz notifications hotfix.

Usage:
    python apply_assignhub_quiz_submission_fix.py --check
    python apply_assignhub_quiz_submission_fix.py --apply

Does not modify assignment, course, timed-writing, plagiarism or authentication logic.
Only touches the installed quiz app plus one additional notification kind.
"""
from __future__ import annotations

import argparse
import hashlib
from datetime import datetime
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent

JS = r'''/* AssignHub quiz submit + autosave: server remains authoritative. */
(function () {
  'use strict';
  const root = document.getElementById('ahq-attempt');
  if (!root) return;
  const status = document.getElementById('ahq-status');
  const nearSubmit = document.getElementById('ahq-submit-status');
  const timer = document.getElementById('ahq-clock');
  const submitForm = document.getElementById('ahq-submit-form');
  const submitButton = document.getElementById('ahq-submit');
  const token = document.querySelector('#ahq-csrf-form input[name="csrfmiddlewaretoken"]');
  if (!submitForm || !submitButton || !token) return; // Native POST still works without JS.
  const csrf = token.value;
  const expiry = Number(root.dataset.expiry);
  const serverOffset = Number(root.dataset.serverNow) * 1000 - Date.now();
  const radios = Array.from(document.querySelectorAll('#ahq-attempt input[data-question]'));
  const queues = new Map();
  let expired = false;
  let submitting = false;

  function tell(message, isError) {
    status.textContent = message;
    if (nearSubmit) {
      nearSubmit.textContent = message;
      nearSubmit.classList.toggle('text-danger', !!isError);
      nearSubmit.classList.toggle('text-success', !isError);
    }
  }

  function postForm() {
    // Bypass the async submit listener. Native browser POST includes Django CSRF.
    HTMLFormElement.prototype.submit.call(submitForm);
  }

  function secondsLeft() {
    return Math.max(0, Math.ceil((expiry * 1000 - (Date.now() + serverOffset)) / 1000));
  }

  function clock() {
    const remaining = secondsLeft();
    timer.textContent = `${String(Math.floor(remaining / 60)).padStart(2, '0')}:${String(remaining % 60).padStart(2, '0')}`;
    timer.classList.toggle('urgent', remaining <= 60);
    if (remaining === 0 && !expired) {
      expired = true;
      submitting = true;
      submitButton.disabled = true;
      radios.forEach(input => { input.disabled = true; });
      tell('Time has ended. The server is finalizing saved answers.', false);
      // An expired attempt must always be settled, even if a late autosave fails.
      postForm();
    }
  }

  async function save(question, choice) {
    if (expired) return; // Only the server can accept answers until expiry.
    const response = await fetch(root.dataset.answerUrl, {
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: {
        'X-CSRFToken': csrf,
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json'
      },
      body: new URLSearchParams({question_id: String(question), choice: String(choice)})
    });
    if (response.status === 409) {
      window.location.assign(root.dataset.resultUrl);
      throw new Error('Attempt already finished');
    }
    if (!response.ok) throw new Error('Autosave HTTP ' + response.status);
    const body = await response.json();
    if (!body.saved) throw new Error('Answer not confirmed saved');
  }

  radios.forEach(input => {
    input.addEventListener('change', () => {
      if (expired || submitting) return;
      const question = input.dataset.question;
      const choice = input.value;
      const preceding = queues.get(question) || Promise.resolve();
      tell('Saving your answer...', false);
      // Serialize writes for a single question; a late response cannot overwrite a newer choice.
      const task = preceding.catch(() => {}).then(() => save(question, choice));
      queues.set(question, task);
      task.then(() => {
        if (queues.get(question) === task && !submitting) tell('Answer saved.', false);
      }).catch(() => {
        if (queues.get(question) === task && !submitting) {
          tell('Answer could not be saved. Retry by selecting the answer again, or press Submit to retry.', true);
        }
      });
    });
  });

  submitForm.addEventListener('submit', async event => {
    event.preventDefault();
    if (submitting || expired) return;
    submitting = true;
    submitButton.disabled = true;
    radios.forEach(input => { input.disabled = true; });
    tell('Checking and saving your final answers...', false);
    try {
      const outstanding = [...queues.entries()];
      const settled = await Promise.allSettled(outstanding.map(([, promise]) => promise));
      const retry = outstanding.filter(([, p], i) => settled[i].status === 'rejected');
      if (retry.length) {
        // Explicitly retry ONLY previously failed questions with the most recent choice.
        for (const [qid] of retry) {
          const current = radios.find(input => input.dataset.question === qid && input.checked);
          if (!current) throw new Error('Missing answer after autosave error');
          const response = await fetch(root.dataset.answerUrl, {
            method: 'POST', credentials: 'same-origin', cache: 'no-store',
            headers: {'X-CSRFToken': csrf, 'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'},
            body: new URLSearchParams({question_id: String(qid), choice: current.value})
          });
          if (response.status === 409) { window.location.assign(root.dataset.resultUrl); return; }
          if (!response.ok || !(await response.json()).saved) throw new Error('Failed to save answer ' + qid);
        }
      }
      tell('Answers saved. Submitting quiz...', false);
      postForm();
    } catch (_error) {
      if (secondsLeft() === 0) {
        tell('Time finished. Submitting already saved answers...', false);
        postForm();
        return;
      }
      submitting = false;
      submitButton.disabled = false;
      radios.forEach(input => { input.disabled = false; });
      tell('Could not confirm all answers were saved. Check your internet and press Submit again.', true);
    }
  });
  clock();
  window.setInterval(clock, 1000);
})();
'''

NOTICE_EVENTS = '''"""In-app Quiz notifications. Additive; never changes grades or quiz state."""

import logging

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from courses.models import CourseEnrollment
from notifications.models import Notification
from .models import Quiz, QuizAttempt

logger = logging.getLogger(__name__)


def _put(recipient_id, *, event_key, title, message, target_url):
    if not target_url.startswith('/') or target_url.startswith('//'):
        raise ValueError('Quiz notification destination must be internal')
    Notification.objects.get_or_create(
        event_key=event_key,
        defaults={
            'recipient_id': recipient_id,
            'kind': Notification.Kind.QUIZ,
            'title': title[:160],
            'message': message[:350],
            'target_url': target_url,
        },
    )


def quiz_published(quiz_id):
    quiz = Quiz.objects.select_related('course_offering').filter(
        pk=quiz_id, status=Quiz.Status.PUBLISHED
    ).first()
    if not quiz or not quiz.course_offering.is_active:
        return
    enrolled = CourseEnrollment.objects.filter(
        offering_id=quiz.course_offering_id,
        status=CourseEnrollment.Status.ACTIVE,
        student__is_active=True,
    ).values_list('student_id', flat=True).distinct()
    url = reverse('quizzes:detail', args=[quiz.pk])
    notices = [Notification(
        recipient_id=student_id,
        kind=Notification.Kind.QUIZ,
        title='New course quiz published',
        message=f'{quiz.title} is available in your course.',
        target_url=url,
        event_key=f'quiz:published:{quiz.pk}:{student_id}',
    ) for student_id in enrolled]
    Notification.objects.bulk_create(notices, ignore_conflicts=True, batch_size=400)


def attempt_completed(attempt_id):
    attempt = QuizAttempt.objects.select_related('quiz__created_by', 'student').filter(
        pk=attempt_id,
        status__in=[QuizAttempt.Status.SUBMITTED, QuizAttempt.Status.AUTO_SUBMITTED],
    ).first()
    if not attempt:
        return
    quiz = attempt.quiz
    auto = attempt.status == QuizAttempt.Status.AUTO_SUBMITTED
    if attempt.student.is_active:
        _put(
            attempt.student_id, event_key=f'quiz:received:{attempt.pk}',
            title='Quiz submitted successfully' if not auto else 'Quiz time ended — answers submitted',
            message=f'Your attempt for {quiz.title} has been received. Your saved answers are recorded.',
            target_url=reverse('quizzes:result', args=[quiz.pk]),
        )
    if quiz.created_by.is_active:
        _put(
            quiz.created_by_id, event_key=f'quiz:teacher:submission:{attempt.pk}',
            title='Student quiz attempt submitted',
            message=f'{attempt.student.get_full_name() or attempt.student.username} completed {quiz.title}.',
            target_url=reverse('quizzes:roster', args=[quiz.pk]),
        )
    result_available_to_student(attempt_id)


def result_available_to_student(attempt_id):
    attempt = QuizAttempt.objects.select_related('quiz', 'student').filter(
        pk=attempt_id,
        status__in=[QuizAttempt.Status.SUBMITTED, QuizAttempt.Status.AUTO_SUBMITTED],
        student__is_active=True,
        quiz__show_results=True,
    ).filter(Q(quiz__status=Quiz.Status.CLOSED) | Q(quiz__closes_at__lte=timezone.now())).first()
    if not attempt:
        return False
    _put(
        attempt.student_id,
        event_key=f'quiz:result:released:{attempt.pk}',
        title='Quiz result available',
        message=f'Your result for {attempt.quiz.title} is now available.',
        target_url=reverse('quizzes:result', args=[attempt.quiz_id]),
    )
    return True


def quiz_results_released(quiz_id):
    quiz = Quiz.objects.filter(pk=quiz_id, show_results=True).filter(
        Q(status=Quiz.Status.CLOSED) | Q(closes_at__lte=timezone.now())
    ).first()
    if not quiz:
        return
    ids = QuizAttempt.objects.filter(
        quiz_id=quiz_id, status__in=[QuizAttempt.Status.SUBMITTED, QuizAttempt.Status.AUTO_SUBMITTED]
    ).values_list('pk', flat=True)
    for attempt_id in ids.iterator(chunk_size=200):
        result_available_to_student(attempt_id)


def send_released_result_notices():
    """Idempotent scheduled sweep for quizzes that close by clock, not by teacher."""
    eligible = QuizAttempt.objects.filter(
        status__in=[QuizAttempt.Status.SUBMITTED, QuizAttempt.Status.AUTO_SUBMITTED],
        quiz__show_results=True,
    ).filter(Q(quiz__status=Quiz.Status.CLOSED) | Q(quiz__closes_at__lte=timezone.now()))
    notified = 0
    for attempt_id in eligible.values_list('pk', flat=True).iterator(chunk_size=200):
        if Notification.objects.filter(event_key=f'quiz:result:released:{attempt_id}').exists():
            continue
        notified += int(result_available_to_student(attempt_id))
    return notified
'''

SIGNALS = '''"""Quiz publication / submission transitions -> in-app notifications."""

import logging

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Quiz, QuizAttempt
from . import notice_events

logger = logging.getLogger(__name__)


def _on_commit(fn, *args):
    def deliver():
        try:
            fn(*args)
        except Exception:
            logger.exception('Quiz notification delivery failed: %s', fn.__name__)
    transaction.on_commit(deliver, robust=True)


@receiver(pre_save, sender=Quiz, dispatch_uid='assignhub.quizzes.notice.before')
def before_quiz_save(sender, instance, **kwargs):
    instance._ahq_previous = (
        sender.objects.filter(pk=instance.pk).values('status', 'show_results').first()
        if instance.pk else None
    )


@receiver(post_save, sender=Quiz, dispatch_uid='assignhub.quizzes.notice.after')
def after_quiz_save(sender, instance, created, update_fields, **kwargs):
    changed_fields = set(update_fields) if update_fields is not None else None
    old = getattr(instance, '_ahq_previous', None)
    prev_status = old['status'] if old else None
    if (changed_fields is None or 'status' in changed_fields):
        if instance.status == Quiz.Status.PUBLISHED and prev_status != Quiz.Status.PUBLISHED:
            _on_commit(notice_events.quiz_published, instance.pk)
        if instance.status == Quiz.Status.CLOSED and prev_status != Quiz.Status.CLOSED:
            _on_commit(notice_events.quiz_results_released, instance.pk)
    if (changed_fields is None or 'show_results' in changed_fields):
        if instance.show_results and old is not None and not old['show_results']:
            _on_commit(notice_events.quiz_results_released, instance.pk)


@receiver(post_save, sender=QuizAttempt, dispatch_uid='assignhub.quizzes.notice.attempt')
def after_attempt_save(sender, instance, created, update_fields, **kwargs):
    if instance.status not in [QuizAttempt.Status.SUBMITTED, QuizAttempt.Status.AUTO_SUBMITTED]:
        return
    if update_fields is not None and 'status' not in update_fields:
        return
    # Unique event keys guarantee one alert per completed attempt on retry.
    _on_commit(notice_events.attempt_completed, instance.pk)
'''

TESTS = '''"""Regression coverage for new quiz notification hooks and submission result UI."""

from datetime import timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assignments.tests import AssignmentTestBase
from notifications.models import Notification
from quizzes.models import Quiz, QuizAttempt, QuizQuestion
from quizzes.notice_events import send_released_result_notices


class QuizNotificationIntegrationTests(AssignmentTestBase):
    def _quiz(self, *, status=Quiz.Status.DRAFT, show_results=True):
        quiz = Quiz.objects.create(
            course_offering=self.offering, created_by=self.teacher,
            title='Quiz notification integration test',
            opens_at=timezone.now() - timedelta(minutes=5),
            closes_at=timezone.now() + timedelta(minutes=60),
            duration_minutes=30, status=status, show_results=show_results,
        )
        QuizQuestion.objects.create(
            quiz=quiz, text='2+2?', option_a='1', option_b='4',
            option_c='3', option_d='5', correct_choice='B', points=2,
        )
        return quiz

    def test_publish_notifies_only_active_enrolled_students_once(self):
        quiz = self._quiz()
        with self.captureOnCommitCallbacks(execute=True):
            quiz.status = Quiz.Status.PUBLISHED
            quiz.save(update_fields=['status', 'updated_at'])
        self.assertEqual(Notification.objects.filter(kind=Notification.Kind.QUIZ, title='New course quiz published').count(), 2)
        self.assertFalse(Notification.objects.filter(recipient=self.teacher, title='New course quiz published').exists())
        with self.captureOnCommitCallbacks(execute=True):
            quiz.save(update_fields=['title'])
        self.assertEqual(Notification.objects.filter(title='New course quiz published').count(), 2)

    def test_submit_confirms_result_page_and_notifies_student_and_teacher(self):
        quiz = self._quiz(status=Quiz.Status.PUBLISHED)
        self.client.force_login(self.student)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('quizzes:start', args=[quiz.pk]))
            response = self.client.post(reverse('quizzes:submit', args=[quiz.pk]), follow=True)
        self.assertContains(response, 'Quiz submission confirmed')
        self.assertTrue(Notification.objects.filter(recipient=self.student, title='Quiz submitted successfully').exists())
        self.assertTrue(Notification.objects.filter(recipient=self.teacher, title='Student quiz attempt submitted').exists())
        self.assertFalse(Notification.objects.filter(title='Quiz result available').exists())
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('quizzes:submit', args=[quiz.pk]))
        self.assertEqual(Notification.objects.filter(title='Quiz submitted successfully').count(), 1)

    def test_teacher_close_releases_results_without_exposing_before_close(self):
        quiz = self._quiz(status=Quiz.Status.PUBLISHED)
        self.client.force_login(self.student)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('quizzes:start', args=[quiz.pk]))
            self.client.post(reverse('quizzes:submit', args=[quiz.pk]))
        self.client.force_login(self.teacher)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('quizzes:close', args=[quiz.pk]))
        self.assertEqual(Notification.objects.filter(recipient=self.student, title='Quiz result available').count(), 1)
        self.assertEqual(send_released_result_notices(), 0)

    def test_unreleased_result_notification_is_not_sent(self):
        quiz = self._quiz(status=Quiz.Status.PUBLISHED, show_results=False)
        self.client.force_login(self.student)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('quizzes:start', args=[quiz.pk]))
            self.client.post(reverse('quizzes:submit', args=[quiz.pk]))
        quiz.status = Quiz.Status.CLOSED
        with self.captureOnCommitCallbacks(execute=True):
            quiz.save(update_fields=['status'])
        self.assertFalse(Notification.objects.filter(title='Quiz result available').exists())
'''


def replace_once(src: str, old: str, new: str, label: str) -> str:
    if new in src:
        return src
    if src.count(old) != 1:
        raise RuntimeError(f'{label}: expected anchor not found exactly once (different/modified source).')
    return src.replace(old, new, 1)


def build_plan():
    paths = {
        'apps': ROOT / 'quizzes' / 'apps.py',
        'take': ROOT / 'templates' / 'quizzes' / 'take.html',
        'result': ROOT / 'templates' / 'quizzes' / 'result.html',
        'js': ROOT / 'static' / 'js' / 'quizzes.js',
        'notification_model': ROOT / 'notifications' / 'models.py',
        'expiry_worker': ROOT / 'quizzes' / 'management' / 'commands' / 'finalize_quiz_attempts.py',
    }
    for label, path in paths.items():
        if not path.is_file():
            raise RuntimeError(f'Missing {label}: {path.relative_to(ROOT)}. Install Quiz Part 1 first.')

    updates = {}

    p = paths['apps']
    old = p.read_text(encoding='utf-8')
    new = replace_once(old,
        "    verbose_name = 'AssignHub Quiz System'",
        "    verbose_name = 'AssignHub Quiz System'\n\n    def ready(self):\n        from . import signals  # noqa: F401",
        'Quiz app signal registration')
    if new != old: updates[p] = new

    p = paths['take']
    old = p.read_text(encoding='utf-8')
    new = replace_once(old,
        '</button></form>\n</section>',
        '</button><div id="ahq-submit-status" class="small text-muted mt-2" role="status" aria-live="polite">After submission, you will be redirected to a confirmation page.</div></form>\n</section>',
        'Submit button feedback')
    if new != old: updates[p] = new

    p = paths['result']
    old = p.read_text(encoding='utf-8')
    new = replace_once(old,
        '<h1>{{ quiz.title }}</h1><p>Submission status:',
        '<h1>{{ quiz.title }}</h1><div class="alert alert-success mt-3" role="status"><strong>Quiz submission confirmed.</strong> {% if attempt.status == "AUTO_SUBMITTED" %}Time ended and your saved answers were submitted automatically.{% else %}Your final answers have been received successfully.{% endif %}</div><p>Submission status:',
        'Result confirmation banner')
    if new != old: updates[p] = new

    p = paths['js']
    old = p.read_text(encoding='utf-8')
    if '/* AssignHub quiz submit + autosave: server remains authoritative. */' not in old:
        expected_sha256 = '32a60f31456e58a539915ca7b61e94bc5360dd4da48d4d506e24b7d292b32c8a'
        if hashlib.sha256(old.encode('utf-8')).hexdigest() != expected_sha256:
            raise RuntimeError('Quiz JavaScript differs from the known Part 1 version; refusing to overwrite custom changes.')
        updates[p] = JS

    p = paths['notification_model']
    old = p.read_text(encoding='utf-8')
    new = replace_once(old,
        '        ASSIGNMENT = "ASSIGNMENT", "Assignment Published"',
        '        ASSIGNMENT = "ASSIGNMENT", "Assignment Published"\n        QUIZ = "QUIZ", "Quiz Activity"',
        'Quiz notification kind')
    if new != old: updates[p] = new

    p = paths['expiry_worker']
    old = p.read_text(encoding='utf-8')
    new = replace_once(old,
        "        self.stdout.write(self.style.SUCCESS(f'Finalized {n} quiz attempt(s).'))",
        "        from quizzes.notice_events import send_released_result_notices\n        alerts = send_released_result_notices()\n        self.stdout.write(self.style.SUCCESS(f'Finalized {n} quiz attempt(s); sent {alerts} new result notification(s).'))",
        'Quiz expiry results notifications')
    if new != old: updates[p] = new

    adds = {
        ROOT / 'quizzes' / 'notice_events.py': NOTICE_EVENTS,
        ROOT / 'quizzes' / 'signals.py': SIGNALS,
        ROOT / 'quizzes' / 'test_notification_integration.py': TESTS,
    }
    for p, content in list(adds.items()):
        if p.exists():
            if not p.is_file() or p.read_text(encoding='utf-8') != content:
                raise RuntimeError(f'Refusing to overwrite existing customized file: {p.relative_to(ROOT)}')
            del adds[p]
    return updates, adds


def main():
    parser = argparse.ArgumentParser(description='Targeted Quiz submit UX + notification integration repair')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true', help='Preview only')
    group.add_argument('--apply', action='store_true', help='Back up and install')
    args = parser.parse_args()
    if not (ROOT / 'manage.py').is_file():
        sys.exit('ERROR: Put this file beside manage.py in the AssignHub main folder.')
    try:
        updates, adds = build_plan()
        print('AssignHub Quiz Submission / Notifications FIX')
        print('Update:', len(updates), 'existing files; add:', len(adds), 'new files')
        for p in updates: print('  UPDATE', p.relative_to(ROOT))
        for p in adds: print('  ADD   ', p.relative_to(ROOT))
        if args.check:
            print('DRY RUN: no files changed.')
            return
        if not (updates or adds):
            print('Already installed. No changes.')
            return
        backup = ROOT.parent / 'AssignHub_Quiz_Fix_Backups' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        for p in updates:
            dest = backup / p.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
        for p, text in {**updates, **adds}.items():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding='utf-8')
        print('Backup directory:', backup)
        print('NEXT: python manage.py makemigrations notifications')
        print('NEXT: python manage.py migrate')
        print('NEXT: python manage.py check')
        print('NEXT: python manage.py test quizzes notifications')
        print('NEXT: restart server; for scheduled result alerts run finalize_quiz_attempts every minute.')
    except Exception as exc:
        sys.exit('No changes applied. ' + str(exc))


if __name__ == '__main__':
    main()
