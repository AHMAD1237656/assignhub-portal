"""Additive AI Part 2 regression tests (no external model/network needed)."""
from datetime import timedelta
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from assignments.tests import AssignmentTestBase
from quizzes.models import Quiz, QuizQuestion, QuizAttempt
from .forms import PolicyForm
from .models import MonitoringEvent, MonitoringSession, ProctoringPolicy


class ProctorAIIntegrationTests(AssignmentTestBase):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.quiz = Quiz.objects.create(
            course_offering=self.offering, created_by=self.teacher, title='AI Integration Test',
            opens_at=now - timedelta(minutes=2), closes_at=now + timedelta(hours=2),
            duration_minutes=25, status=Quiz.Status.PUBLISHED,
        )
        QuizQuestion.objects.create(quiz=self.quiz, text='Demo?', option_a='Yes', option_b='No',
                                    option_c='Maybe', option_d='Other', correct_choice='A')
        self.policy = ProctoringPolicy.objects.create(quiz=self.quiz, enabled=True, require_camera=True)

    def u(self, name, *args):
        return reverse('quiz_proctoring:' + name, args=args)

    def _start(self):
        self.client.force_login(self.student)
        response = self.client.post(self.u('device_check', self.quiz.pk),
                                    {'consent':'yes', 'camera_checked':'yes'})
        self.assertEqual(response.status_code, 302)
        return QuizAttempt.objects.get(quiz=self.quiz, student=self.student)

    def test_legacy_quiz_policy_ai_defaults_to_off(self):
        self.assertFalse(self.policy.ai_enabled)
        self.assertTrue(self.policy.detect_phone)
        self.assertTrue(self.policy.detect_multiple_faces)

    def test_teacher_form_ai_requires_camera_and_monitoring(self):
        values = {'ai_enabled':'on', 'detect_phone':'on', 'detect_multiple_faces':'on',
                  'detect_face_absence':'on', 'detect_head_movement':'on'}
        form = PolicyForm(data=values, instance=self.policy)
        self.assertFalse(form.is_valid())
        self.assertIn('require_camera', form.errors)
        self.assertIn('enabled', form.errors)

    def test_teacher_can_enable_ai_on_draft_but_not_published(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(self.u('settings', self.quiz.pk)).status_code, 403)
        self.quiz.status = Quiz.Status.DRAFT
        self.quiz.save(update_fields=['status'])
        response = self.client.post(self.u('settings', self.quiz.pk), {
            'enabled':'on', 'require_camera':'on', 'log_browser_events':'on',
            'ai_enabled':'on', 'detect_multiple_faces':'on', 'detect_face_absence':'on',
            'detect_head_movement':'on', 'detect_phone':'on',
        })
        self.assertEqual(response.status_code, 302)
        self.policy.refresh_from_db()
        self.assertTrue(self.policy.ai_enabled)

    def test_ai_event_denied_until_teacher_enables_ai(self):
        self._start()
        response = self.client.post(self.u('event', self.quiz.pk), {'kind':'PHONE_VISIBLE','confidence':'0.86'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(MonitoringEvent.objects.exists())

    def test_ai_signal_metadata_validated_deduplicated_and_teacher_reviewable(self):
        self.policy.ai_enabled = True
        self.policy.save(update_fields=['ai_enabled'])
        attempt = self._start()
        url = self.u('event', self.quiz.pk)
        payload = {'kind':'PHONE_VISIBLE','duration_s':'5','confidence':'0.86'}
        self.assertEqual(self.client.post(url, payload).status_code, 200)
        self.assertEqual(self.client.post(url, payload).status_code, 200)
        self.assertEqual(MonitoringEvent.objects.count(), 1)
        incident = MonitoringEvent.objects.get()
        self.assertEqual(incident.source, MonitoringEvent.Source.AI)
        self.assertEqual(incident.duration_seconds, 5)
        self.assertAlmostEqual(incident.confidence, 0.86)
        self.assertEqual(incident.session.attempt_id, attempt.pk)
        self.client.force_login(self.teacher)
        detail = self.client.get(self.u('attempt_events', attempt.pk))
        self.assertContains(detail, 'AI signal metadata')
        self.assertContains(detail, 'Possible mobile phone')
        self.assertEqual(self.client.post(self.u('review_event', incident.pk), {'decision':'DISMISSED'}).status_code, 302)

    def test_invalid_ai_metadata_and_policy_options_rejected(self):
        self.policy.ai_enabled = True
        self.policy.detect_phone = False
        self.policy.save(update_fields=['ai_enabled','detect_phone'])
        self._start()
        endpoint = self.u('event', self.quiz.pk)
        self.assertEqual(self.client.post(endpoint, {'kind':'PHONE_VISIBLE'}).status_code, 403)
        for invalid in ['nan','inf','-0.3','1.2','text']:
            response = self.client.post(endpoint, {'kind':'MULTIPLE_FACES','confidence':invalid,'face_count':'2'})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post(endpoint, {'kind':'MULTIPLE_FACES','face_count':'1'}).status_code, 400)
        self.assertFalse(MonitoringEvent.objects.exists())

    def test_browser_event_works_when_ai_is_enabled(self):
        self.policy.ai_enabled = True
        self.policy.save(update_fields=['ai_enabled'])
        self._start()
        res = self.client.post(self.u('event',self.quiz.pk), {'kind':'TAB_HIDDEN'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(MonitoringEvent.objects.get().source, MonitoringEvent.Source.BROWSER)

    def test_no_signal_after_submission(self):
        self.policy.ai_enabled = True
        self.policy.save(update_fields=['ai_enabled'])
        self._start()
        self.client.post(reverse('quizzes:submit', args=[self.quiz.pk]))
        response = self.client.post(self.u('event', self.quiz.pk), {'kind':'NO_FACE'})
        self.assertEqual(response.status_code, 403)

    def test_ai_ui_only_on_enabled_and_active_monitored_attempt(self):
        self.policy.ai_enabled = True
        self.policy.save(update_fields=['ai_enabled'])
        self._start()
        response = self.client.get(reverse('quizzes:take', args=[self.quiz.pk]))
        self.assertContains(response, 'ahp-monitor-root')
        self.assertContains(response, 'ahp-ai-status')
        self.assertContains(response, 'data-ai-enabled="yes"')
        self.assertNotContains(response, 'Correct answer:')

    def test_cross_student_cannot_post_ai_incident(self):
        self.policy.ai_enabled = True
        self.policy.save(update_fields=['ai_enabled'])
        self._start()
        self.client.force_login(self.student2)
        response = self.client.post(self.u('event', self.quiz.pk), {'kind':'NO_FACE'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(MonitoringEvent.objects.exists())

    def test_csrf_protected_ai_event(self):
        self.policy.ai_enabled = True
        self.policy.save(update_fields=['ai_enabled'])
        self._start()
        secured = Client(enforce_csrf_checks=True)
        secured.force_login(self.student)
        response = secured.post(self.u('event', self.quiz.pk), {'kind':'MULTIPLE_FACES'})
        self.assertEqual(response.status_code, 403)
