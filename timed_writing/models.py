from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class TimedWritingConfig(models.Model):
    """
    Optional timed mode for an existing Assignment.
    """

    assignment = models.OneToOneField(
        "assignments.Assignment",
        on_delete=models.CASCADE,
        related_name="timed_writing_config",
    )

    duration_minutes = models.PositiveSmallIntegerField(
        default=30,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(240),
        ],
    )

    is_enabled = models.BooleanField(default=True)

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def clean(self):
        super().clean()

        if self.assignment_id:
            assignment = self.assignment

            if (
                self.is_enabled
                and assignment.status
                != assignment.Status.PUBLISHED
            ):
                raise ValidationError(
                    "Only published assignments "
                    "can enable timed writing."
                )

            if (
                self.is_enabled
                and not assignment.course_offering_id
            ):
                raise ValidationError(
                    "A course offering is required."
                )

        if self.pk and self.attempts.exists():
            original = type(self).objects.get(
                pk=self.pk,
            )

            if (
                original.duration_minutes
                != self.duration_minutes
                or original.is_enabled
                != self.is_enabled
            ):
                raise ValidationError(
                    "Timed settings cannot be changed "
                    "after a student starts."
                )

    def __str__(self):
        return (
            f"{self.assignment.title} - "
            f"{self.duration_minutes} minutes"
        )


class TimedWritingAttempt(models.Model):

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        SUBMITTED = "SUBMITTED", "Submitted"
        EXPIRED = "EXPIRED", "Expired"

    config = models.ForeignKey(
        TimedWritingConfig,
        on_delete=models.PROTECT,
        related_name="attempts",
    )

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="timed_writing_attempts",
    )

    submission = models.OneToOneField(
        "assignments.Submission",
        on_delete=models.PROTECT,
        related_name="timed_attempt",
    )

    started_at = models.DateTimeField(
        default=timezone.now,
        editable=False,
    )

    expires_at = models.DateTimeField(
        editable=False,
    )

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    rich_delta = models.JSONField(
        default=dict,
        blank=True,
    )
    revision = models.PositiveIntegerField(
        default=0,
    )

    auto_submitted = models.BooleanField(
        default=False,
    )

    finalized_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = [
            "-started_at",
            "-pk",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "config",
                    "student",
                ],
                name="unique_timed_config_student",
            ),
        ]

    def clean(self):
        super().clean()

        if self.config_id and self.submission_id:

            if (
                self.config.assignment_id
                != self.submission.assignment_id
            ):
                raise ValidationError(
                    "Attempt and submission must "
                    "belong to the same assignment."
                )

            if (
                self.student_id
                != self.submission.student_id
            ):
                raise ValidationError(
                    "Attempt and submission must "
                    "belong to the same student."
                )

    def save(self, *args, **kwargs):

        if self._state.adding and not self.expires_at:
            duration = timedelta(
                minutes=self.config.duration_minutes
            )

            self.expires_at = min(
                self.started_at + duration,
                self.config.assignment.deadline,
            )

        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.student} - "
            f"{self.config.assignment} - "
            f"{self.status}"
        )