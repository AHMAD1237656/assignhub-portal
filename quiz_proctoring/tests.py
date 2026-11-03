"""Run with python manage.py test quiz_proctoring quizzes notifications."""
from datetime import timedelta
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from assignments.tests import AssignmentTestBase
from quizzes.models import Quiz, QuizQuestion, QuizAttempt
from .models import MonitoringEvent, MonitoringSession, ProctoringPolicy


class ProctoringWorkflowTests(AssignmentTestBase):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.quiz = Quiz.objects.create(
            course_offering=self.offering, created_by=self.teacher, title='AI-monitored Quiz',
            opens_at=now - timedelta(minutes=2), closes_at=now + timedelta(hours=2),
            duration_minutes=20, status=Quiz.Status.DRAFT,
        )
        QuizQuestion.objects.create(quiz=self.quiz, text='Demo?', option_a='a', option_b='b',
                                    option_c='c', option_d='d', correct_choice='A')
        self.policy = ProctoringPolicy.objects.create(quiz=self.quiz, enabled=True, require_camera=True)
        self.quiz.status = Quiz.Status.PUBLISHED
        self.quiz.save(update_fields=['status'])

    def url(self, name, *args):
        return reverse('quiz_proctoring:' + name, args=args)

    def test_class_course_quiz_categorized_and_private(self):
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(self.url('classes')), 'My Classes')
        self.assertEqual(self.client.get(self.url('class_courses', self.section.pk, self.offering.academic_year, self.offering.term)).status_code, 200)
        self.assertContains(self.client.get(self.url('course_quizzes', self.offering.pk)), 'AI-monitored Quiz')
        self.client.force_login(self.teacher2)
        self.assertEqual(self.client.get(self.url('course_quizzes', self.offering.pk)).status_code, 404)
        self.assertEqual(self.client.get(self.url('quiz_monitoring', self.quiz.pk)).status_code, 403)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(self.url('classes')).status_code, 403)

    def test_teacher_config_locked_after_publish(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(self.url('settings', self.quiz.pk)).status_code, 403)

    def test_preflight_required_before_attempt_start(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.post(reverse('quizzes:start', args=[self.quiz.pk])).status_code, 302)
        self.assertFalse(QuizAttempt.objects.filter(quiz=self.quiz, student=self.student).exists())
        self.assertEqual(self.client.get(self.url('device_check', self.quiz.pk)).status_code, 200)
        self.client.post(self.url('device_check', self.quiz.pk), {'consent':'yes', 'camera_checked':'no'})
        self.assertFalse(QuizAttempt.objects.filter(quiz=self.quiz, student=self.student).exists())
        response = self.client.post(self.url('device_check', self.quiz.pk), {'consent':'yes', 'camera_checked':'yes'})
        self.assertEqual(response.status_code, 302)
        attempt = QuizAttempt.objects.get(quiz=self.quiz, student=self.student)
        self.assertTrue(MonitoringSession.objects.filter(attempt=attempt, camera_check_claimed=True).exists())
        self.assertContains(self.client.get(reverse('quizzes:take', args=[self.quiz.pk])), 'ahp-monitor-root')

    def test_only_owner_can_record_and_review_events(self):
        self.client.force_login(self.student)
        self.client.post(self.url('device_check', self.quiz.pk), {'consent':'yes','camera_checked':'yes'})
        self.assertEqual(self.client.post(self.url('event', self.quiz.pk), {'kind':'NOT_A_REAL_EVENT'}).status_code, 400)
        self.assertEqual(self.client.post(self.url('event', self.quiz.pk), {'kind':'TAB_HIDDEN'}).status_code, 200)
        self.client.post(self.url('event', self.quiz.pk), {'kind':'TAB_HIDDEN'})
        self.assertEqual(MonitoringEvent.objects.count(), 1)
        event = MonitoringEvent.objects.first()
        self.assertEqual(self.client.post(self.url('review_event', event.pk), {'decision':'REVIEWED'}).status_code, 403)
        self.client.force_login(self.student2)
        self.assertEqual(self.client.post(self.url('event', self.quiz.pk), {'kind':'TAB_HIDDEN'}).status_code, 403)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.post(self.url('review_event', event.pk), {'decision':'REVIEWED'}).status_code, 302)
        event.refresh_from_db()
        self.assertEqual(event.review_status, MonitoringEvent.Review.REVIEWED)

    def test_completed_attempt_does_not_accept_events(self):
        self.client.force_login(self.student)
        self.client.post(self.url('device_check', self.quiz.pk), {'consent':'yes','camera_checked':'yes'})
        self.client.post(reverse('quizzes:submit', args=[self.quiz.pk]))
        self.assertEqual(self.client.post(self.url('event', self.quiz.pk), {'kind':'TAB_HIDDEN'}).status_code, 403)
        self.assertIsNotNone(MonitoringSession.objects.get(attempt__quiz=self.quiz).closed_at)

    def test_unmonitored_quiz_uses_original_start(self):
        self.policy.enabled = False
        self.policy.save(update_fields=['enabled'])
        self.client.force_login(self.student)
        self.assertEqual(self.client.post(reverse('quizzes:start', args=[self.quiz.pk])).status_code, 302)
        self.assertEqual(MonitoringSession.objects.count(), 0)
        self.assertNotContains(self.client.get(reverse('quizzes:take', args=[self.quiz.pk])), 'ahp-monitor-root')

    def test_csrf_write_endpoint_and_no_camera_data(self):
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.student)
        self.assertEqual(guarded.post(self.url('device_check', self.quiz.pk), {'consent':'yes','camera_checked':'yes'}).status_code, 403)
        self.assertFalse(QuizAttempt.objects.filter(quiz=self.quiz, student=self.student).exists())

    def test_administrator_readonly(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url('quiz_monitoring', self.quiz.pk)).status_code, 200)
        self.assertEqual(self.client.post(self.url('settings', self.quiz.pk), {'enabled':'on'}).status_code, 403)

    def test_camera_off_policy_allows_explicit_consent(self):
        self.policy.require_camera = False
        self.policy.save(update_fields=['require_camera'])
        self.client.force_login(self.student)
        self.client.post(self.url('device_check', self.quiz.pk), {'consent':'yes','camera_checked':'no'})
        self.assertTrue(MonitoringSession.objects.filter(attempt__student=self.student, camera_check_claimed=False).exists())
