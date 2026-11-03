"""Server-side policy and attempt access checks shared by proctoring endpoints."""
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from assignments.permissions import is_admin, is_teacher
from quizzes.models import QuizAttempt
from quizzes.services import student_can_see
from .models import MonitoringSession, ProctoringPolicy


def is_proctored(quiz):
    return ProctoringPolicy.objects.filter(quiz_id=quiz.pk, enabled=True).exists()


def can_review(user, quiz):
    return is_admin(user) or (is_teacher(user) and quiz.created_by_id == user.pk and quiz.course_offering.teacher_id == user.pk)


def require_review(user, quiz):
    if not can_review(user, quiz):
        raise PermissionDenied('Only the assigned teacher or administrator can review monitoring.')


def open_session(attempt, *, camera_check_claimed):
    session, _ = MonitoringSession.objects.get_or_create(
        attempt=attempt,
        defaults={'consent_at': timezone.now(), 'camera_check_claimed': bool(camera_check_claimed)},
    )
    return session


def active_student_session(user, quiz):
    if not student_can_see(user, quiz):
        raise PermissionDenied('Not enrolled in this course.')
    attempt = QuizAttempt.objects.filter(quiz=quiz, student=user).first()
    if not attempt:
        raise PermissionDenied('No exam attempt is active.')
    try:
        session = attempt.monitoring_session
    except MonitoringSession.DoesNotExist:
        raise PermissionDenied('No monitoring session exists for this attempt.')
    if attempt.status != QuizAttempt.Status.IN_PROGRESS or timezone.now() >= attempt.expires_at or quiz.status != quiz.Status.PUBLISHED:
        raise PermissionDenied('Exam monitoring session has finished.')
    return session
