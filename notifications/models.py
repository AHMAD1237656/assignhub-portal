from django.conf import settings
from django.db import models


class Notification(models.Model):
    """Private, durable, recipient-scoped in-app notification."""

    class Kind(models.TextChoices):
        ASSIGNMENT = "ASSIGNMENT", "Assignment Published"
        ASSIGNMENT_CLOSED = "CLOSED", "Assignment Closed"
        SUBMISSION = "SUBMISSION", "Submission Received"
        GRADE = "GRADE", "Grade Available"
        PLAGIARISM = "PLAGIARISM", "Integrity Review"
        DEADLINE = "DEADLINE", "Deadline Reminder"
        ACTIVATION = "ACTIVATION", "Student Activated"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="assignhub_notifications",
        on_delete=models.CASCADE,
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    title = models.CharField(max_length=160)
    message = models.CharField(max_length=350)
    # Only server-generated, site-relative routes are allowed here.
    target_url = models.CharField(max_length=500)
    # Prevent duplicate alerts after retries, refreshes or repeated scheduling.
    event_key = models.CharField(max_length=190, unique=True)
    read_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(
                fields=["recipient", "read_at", "-created_at"],
                name="ah_notice_user_read_idx",
            ),
        ]

    @property
    def is_read(self):
        return self.read_at is not None

    def __str__(self):
        return f"{self.recipient_id}: {self.get_kind_display()} - {self.title}"
