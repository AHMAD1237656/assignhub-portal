import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from courses.models import (
    CourseOffering,
    validate_academic_year,
)
from semesters.models import Section


def generate_activation_nonce():
    return secrets.token_urlsafe(32)


class StudentImportBatch(models.Model):

    class Status(models.TextChoices):
        PREVIEW = "PREVIEW", "Preview"
        CONFIRMED = "CONFIRMED", "Confirmed"

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="student_import_batches",
    )

    filename = models.CharField(
        max_length=255,
    )

    section = models.ForeignKey(
        Section,
        on_delete=models.PROTECT,
        related_name="student_import_batches",
    )

    academic_year = models.CharField(
        max_length=9,
        validators=[validate_academic_year],
    )

    term = models.CharField(
        max_length=10,
        choices=CourseOffering.Term.choices,
    )

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PREVIEW,
    )

    # Temporary preview data.
    # Cleared after successful confirmation.
    rows = models.JSONField(
        default=list,
        blank=True,
    )

    row_count = models.PositiveIntegerField(
        default=0,
    )

    created_count = models.PositiveIntegerField(
        default=0,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return (
            f"Student Import #{self.pk} "
            f"({self.academic_year} {self.term})"
        )

    @property
    def is_expired(self):
        return timezone.now() > (
            self.created_at + timedelta(hours=24)
        )

    @property
    def error_count(self):
        return sum(
            bool(row.get("errors"))
            for row in self.rows
        )

    @property
    def valid_count(self):
        return sum(
            not row.get("errors")
            for row in self.rows
        )


class StudentIdentity(models.Model):

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending Activation"
        ACTIVE = "ACTIVE", "Activated"

    class EmailStatus(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        SENDING = "SENDING", "Sending"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="student_identity",
    )

    import_batch = models.ForeignKey(
        StudentImportBatch,
        on_delete=models.PROTECT,
        related_name="identities",
    )

    roll_number = models.CharField(
        max_length=40,
    )

    institutional_email = models.EmailField()

    section = models.ForeignKey(
        Section,
        on_delete=models.PROTECT,
        related_name="imported_student_identities",
    )

    academic_year = models.CharField(
        max_length=9,
        validators=[validate_academic_year],
    )

    term = models.CharField(
        max_length=10,
        choices=CourseOffering.Term.choices,
    )

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )

    activation_nonce = models.CharField(
        max_length=80,
        default=generate_activation_nonce,
    )

    email_status = models.CharField(
        max_length=10,
        choices=EmailStatus.choices,
        default=EmailStatus.QUEUED,
    )

    email_claimed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    email_sent_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    activated_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["roll_number"]

        constraints = [
            models.UniqueConstraint(
                Lower("roll_number"),
                name="student_roll_number_ci_unique",
            ),
            models.UniqueConstraint(
                Lower("institutional_email"),
                name="student_email_ci_unique",
            ),
        ]

        indexes = [
            models.Index(
                fields=["status", "email_status"],
                name="student_activation_queue_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.roll_number} - "
            f"{self.user.username}"
        )