from django.core.exceptions import (
    PermissionDenied,
    ValidationError,
)
from django.db import transaction
from django.utils import timezone
from .richtext import normalize_delta
from assignments.models import Assignment, Submission
from assignments.permissions import is_student
from assignments.views import student_has_course_access

from .models import (
    TimedWritingAttempt,
    TimedWritingConfig,
)


MAX_ANSWER_LENGTH = 100_000


def enforce_student(student, assignment):
    """
    Only enrolled students can attempt an assignment.
    """

    if not is_student(student):
        raise PermissionDenied(
            "Student access required."
        )

    if not student_has_course_access(
        student,
        assignment,
    ):
        raise PermissionDenied(
            "Active course enrollment is required."
        )


def enforce_config(assignment):
    """
    Ensure timed writing is enabled.
    """

    try:
        config = assignment.timed_writing_config

    except TimedWritingConfig.DoesNotExist:
        raise PermissionDenied(
            "Timed writing is not configured."
        )

    if not config.is_enabled:
        raise PermissionDenied(
            "Timed writing is disabled."
        )

    return config


@transaction.atomic
def begin(assignment_pk, student):
    """
    Start one attempt and persist its deadline.

    Repeated requests cannot reset the timer.
    """

    assignment = (
        Assignment.objects
        .select_for_update()
        .get(pk=assignment_pk)
    )

    enforce_student(student, assignment)

    config = enforce_config(assignment)

    attempt = (
        TimedWritingAttempt.objects
        .select_for_update()
        .filter(
            config=config,
            student=student,
        )
        .first()
    )

    if attempt:
        return settle_if_expired(attempt)

    if not assignment.is_open:
        raise PermissionDenied(
            "Assignment deadline has passed."
        )

    if Submission.objects.filter(
        assignment=assignment,
        student=student,
    ).exists():
        raise PermissionDenied(
            "An earlier submission already exists."
        )

    submission = Submission.objects.create(
        assignment=assignment,
        student=student,
        status=Submission.Status.DRAFT,
        text_content="",
    )

    attempt = TimedWritingAttempt(
        config=config,
        student=student,
        submission=submission,
        started_at=timezone.now(),
    )

    attempt.full_clean(
        exclude=["expires_at"]
    )

    attempt.save()

    return attempt


def settle_if_expired(attempt):
    """
    Must be called inside an atomic transaction
    while holding the attempt's database row lock.
    """

    if (
        attempt.status
        == TimedWritingAttempt.Status.ACTIVE
        and timezone.now() >= attempt.expires_at
    ):

        submission = (
            Submission.objects
            .select_for_update()
            .get(pk=attempt.submission_id)
        )

        if submission.text_content.strip():

            submission.status = (
                Submission.Status.SUBMITTED
            )

            submission.submitted_at = (
                attempt.expires_at
            )

            submission.full_clean()

            submission.save(
                update_fields=[
                    "status",
                    "submitted_at",
                    "updated_at",
                ]
            )

            attempt.status = (
                TimedWritingAttempt.Status.SUBMITTED
            )

            attempt.auto_submitted = True

        else:

            attempt.status = (
                TimedWritingAttempt.Status.EXPIRED
            )

        attempt.finalized_at = timezone.now()

        attempt.save(
            update_fields=[
                "status",
                "auto_submitted",
                "finalized_at",
                "updated_at",
            ]
        )

    return attempt


@transaction.atomic
def read_attempt(assignment_pk, student):
    """
    Read an attempt and settle expired attempts.
    """

    attempt = (
        TimedWritingAttempt.objects
        .select_for_update()
        .select_related(
            "config__assignment",
            "submission",
        )
        .get(
            config__assignment_id=assignment_pk,
            student=student,
        )
    )

    enforce_student(
        student,
        attempt.config.assignment,
    )

    return settle_if_expired(attempt)


@transaction.atomic
def write_answer(
    assignment_pk,
    student,
    answer,
    revision,
    finalize=False,
    delta=None,
):
    attempt = (
        TimedWritingAttempt.objects
        .select_for_update()
        .select_related(
            "config__assignment",
            "submission",
        )
        .get(
            config__assignment_id=assignment_pk,
            student=student,
        )
    )

    enforce_student(
        student,
        attempt.config.assignment,
    )

    attempt = settle_if_expired(attempt)

    if (
        attempt.status
        != TimedWritingAttempt.Status.ACTIVE
    ):
        return attempt, "closed"

    if revision != attempt.revision:
        return attempt, "conflict"

    if delta is not None:

        # Rich editor: validate and derive
        # plain text on the server.
        normalized_delta, answer = (
            normalize_delta(delta)
        )

    else:

        # Backward compatibility with existing
        # 36 timed-writing tests and plain editor.
        if not isinstance(answer, str):
            raise ValidationError(
                "Invalid answer."
            )

        normalized_delta = {
            "ops": [
                {
                    "insert": answer + "\n"
                }
            ]
        }

    if len(answer) > MAX_ANSWER_LENGTH:
        raise ValidationError(
            "Answer exceeds 100,000 characters."
        )

    if finalize and not answer.strip():
        raise ValidationError(
            "Write an answer before submitting."
        )

    submission = (
        Submission.objects
        .select_for_update()
        .get(pk=attempt.submission_id)
    )

    if submission.status != Submission.Status.DRAFT:
        raise PermissionDenied(
            "Submission is already finalized."
        )

    submission.text_content = answer

    if finalize:
        submission.status = (
            Submission.Status.SUBMITTED
        )

        submission.submitted_at = timezone.now()

    submission.full_clean()

    submission.save(
        update_fields=[
            "text_content",
            "status",
            "submitted_at",
            "updated_at",
        ]
    )

    attempt.rich_delta = normalized_delta
    attempt.revision += 1

    update_fields = [
        "rich_delta",
        "revision",
        "updated_at",
    ]

    if finalize:
        attempt.status = (
            TimedWritingAttempt.Status.SUBMITTED
        )

        attempt.finalized_at = timezone.now()

        update_fields += [
            "status",
            "finalized_at",
        ]

    attempt.save(
        update_fields=update_fields
    )

    return attempt, "ok"