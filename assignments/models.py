from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Assignment(models.Model):

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"
        CLOSED = "CLOSED", "Closed"

    title = models.CharField(
        max_length=255
    )

    instructions = models.TextField()

    attachment = models.FileField(
        upload_to="assignments/attachments/",
        blank=True,
        null=True,
    )

    deadline = models.DateTimeField()

    total_marks = models.PositiveIntegerField(
        default=100
    )

    rubric = models.TextField(
        blank=True
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_assignments",
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    def clean(self):
        errors = {}

        if self.total_marks is not None:
            if self.total_marks < 1:
                errors["total_marks"] = (
                    "Total marks must be at least 1."
                )

        if self.deadline is None:
            errors["deadline"] = (
                "Deadline is required."
            )

        if errors:
            raise ValidationError(errors)

    @property
    def is_overdue(self):
        if self.deadline is None:
            return False

        return timezone.now() > self.deadline

    @property
    def is_open(self):
        return (
            self.status == self.Status.PUBLISHED
            and self.deadline is not None
            and timezone.now() <= self.deadline
        )


class Submission(models.Model):

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        GRADED = "GRADED", "Graded"

    assignment = models.ForeignKey(
        Assignment,
        on_delete=models.CASCADE,
        related_name="submissions",
    )

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assignment_submissions",
    )

    text_content = models.TextField(
        blank=True
    )

    submission_file = models.FileField(
        upload_to="assignments/submissions/",
        blank=True,
        null=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    submitted_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    marks = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        blank=True,
        null=True,
    )

    feedback = models.TextField(
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = ["-created_at"]

        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "student"],
                name=(
                    "unique_assignment_student_submission"
                ),
            )
        ]

    def __str__(self):
        return (
            f"{self.student.username} - "
            f"{self.assignment.title}"
        )

    def clean(self):
        errors = {}

        if self.marks is not None:
            if (
                self.marks < 0
                or self.marks > self.assignment.total_marks
            ):
                errors["marks"] = (
                    "Marks must be between 0 "
                    "and total marks."
                )

        if self.status in (
            self.Status.SUBMITTED,
            self.Status.GRADED,
        ):
            if not self.submitted_at:
                errors["submitted_at"] = (
                    "Finalized submissions require "
                    "a submission timestamp."
                )

            if (
                not self.text_content.strip()
                and not self.submission_file
            ):
                errors["text_content"] = (
                    "Provide text or a PDF submission."
                )

        if errors:
            raise ValidationError(errors)