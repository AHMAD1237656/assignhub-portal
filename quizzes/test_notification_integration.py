"""Regression coverage for new quiz notification hooks and submission result UI."""

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
