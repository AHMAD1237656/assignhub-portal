"""In-app Quiz notifications. Additive; never changes grades or quiz state."""

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
