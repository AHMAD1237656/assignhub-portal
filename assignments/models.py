from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Assignment(models.Model):

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"
        CLOSED = "CLOSED", "Closed"

    title = models.CharField(max_length=255)

    instructions = models.TextField()

    attachment = models.FileField(
        upload_to="assignments/attachments/",
        blank=True,
        null=True,
    )

    deadline = models.DateTimeField()

    total_marks = models.PositiveIntegerField(default=100)

    rubric = models.TextField(
        blank=True,
        help_text="Optional grading rubric.",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_assignments",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @property
    def is_overdue(self):
        return timezone.now() > self.deadline

    @property
    def is_open(self):
        return (
            self.status == self.Status.PUBLISHED
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
        on_delete=models.CASCADE,
        related_name="assignment_submissions",
    )

    text_content = models.TextField(
        blank=True,
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
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "student"],
                name="unique_assignment_student_submission",
            )
        ]

    def clean(self):
        if self.marks is not None and self.marks > self.assignment.total_marks:
            raise ValidationError(
                "Marks cannot be greater than the assignment total marks."
            )

    def __str__(self):
        return f"{self.student.username} - {self.assignment.title}"

    def submit(self):
        if timezone.now() > self.assignment.deadline:
            raise ValidationError(
                "The assignment deadline has passed."
            )

        if not self.text_content.strip() and not self.submission_file:
            raise ValidationError(
                "A text response or submission file is required."
            )

        self.status = self.Status.SUBMITTED
        self.submitted_at = timezone.now()
        self.save()