"""Server-authoritative exam lifecycle. Do not trust the browser timer or score."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from courses.models import CourseEnrollment
from assignments.permissions import is_student
from .models import Quiz, QuizAttempt, QuizAnswer, QuizQuestion


def student_can_see(user, quiz):
    if not is_student(user):
        return False
    return CourseEnrollment.objects.filter(
        student=user, status=CourseEnrollment.Status.ACTIVE,
        offering_id=quiz.course_offering_id, offering__is_active=True,
        offering__course__is_active=True, offering__section__is_active=True,
    ).exists()


def settle_locked(attempt, *, manual=False):
    """Caller must hold a row lock inside transaction.atomic()."""
    if attempt.status != QuizAttempt.Status.IN_PROGRESS:
        return attempt
    now = timezone.now()
    if not manual and now < attempt.expires_at and attempt.quiz.status == Quiz.Status.PUBLISHED:
        return attempt
    answers = {answer.question_id: answer.selected_choice for answer in attempt.answers.all()}
    questions = list(attempt.quiz.questions.all())
    attempt.earned_marks = sum(q.points for q in questions if answers.get(q.pk) == q.correct_choice)
    attempt.total_marks = sum(q.points for q in questions)
    attempt.status = (QuizAttempt.Status.SUBMITTED if manual and now < attempt.expires_at and attempt.quiz.status == Quiz.Status.PUBLISHED
                      else QuizAttempt.Status.AUTO_SUBMITTED)
    attempt.submitted_at = now
    attempt.save(update_fields=['status', 'submitted_at', 'earned_marks', 'total_marks'])
    return attempt


@transaction.atomic
def begin(quiz_id, student):
    quiz = Quiz.objects.select_for_update().select_related('course_offering').get(pk=quiz_id)
    if not student_can_see(student, quiz):
        raise PermissionDenied('You are not enrolled in this quiz course.')
    existing = QuizAttempt.objects.select_for_update().filter(quiz=quiz, student=student).first()
    if existing:
        return settle_locked(existing)
    if not quiz.is_open:
        raise PermissionDenied('Quiz is not open for new attempts.')
    if not quiz.questions.exists():
        raise PermissionDenied('Quiz is not ready.')
    # Quiz row lock serializes a user's concurrent start requests on supported databases.
    return QuizAttempt.objects.create(quiz=quiz, student=student)


@transaction.atomic
def save_choice(attempt_id, student, question_id, choice):
    attempt = QuizAttempt.objects.select_for_update().select_related('quiz').get(pk=attempt_id, student=student)
    settle_locked(attempt)
    if attempt.status != QuizAttempt.Status.IN_PROGRESS:
        return attempt, False
    if not student_can_see(student, attempt.quiz):
        raise PermissionDenied('Enrollment is no longer active.')
    if choice not in QuizQuestion.Choice.values:
        raise ValidationError('Invalid answer choice.')
    question = QuizQuestion.objects.filter(pk=question_id, quiz_id=attempt.quiz_id).first()
    if question is None:
        raise PermissionDenied('This question belongs to another quiz.')
    QuizAnswer.objects.update_or_create(
        attempt=attempt, question=question,
        defaults={'selected_choice': choice},
    )
    return attempt, True


@transaction.atomic
def finish(attempt_id, student):
    attempt = QuizAttempt.objects.select_for_update().select_related('quiz').get(pk=attempt_id, student=student)
    if attempt.status == QuizAttempt.Status.IN_PROGRESS and not student_can_see(student, attempt.quiz):
        raise PermissionDenied('Enrollment is no longer active.')
    settle_locked(attempt, manual=True)
    return attempt


@transaction.atomic
def refresh(attempt_id, student):
    attempt = QuizAttempt.objects.select_for_update().select_related('quiz').get(pk=attempt_id, student=student)
    return settle_locked(attempt)
