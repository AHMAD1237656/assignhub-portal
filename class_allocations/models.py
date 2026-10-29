from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from courses.models import (
    CourseOffering,
    validate_academic_year,
)
from semesters.models import Section


class StudentClassAllocation(models.Model):

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        TRANSFERRED = "TRANSFERRED", "Transferred"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="class_allocations",
    )

    section = models.ForeignKey(
        Section,
        on_delete=models.PROTECT,
        related_name="student_allocations",
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
        default=Status.ACTIVE,
    )

    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="class_allocations_created",
    )

    reason = models.CharField(
        max_length=200,
        blank=True,
    )

    created_at = models.DateTimeField(
        default=timezone.now,
        editable=False,
    )

    ended_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at", "-pk"]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "student",
                    "academic_year",
                    "term",
                ],
                condition=Q(status="ACTIVE"),
                name="unique_active_class_period",
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "section",
                    "academic_year",
                    "term",
                    "status",
                ],
                name="class_alloc_section_idx",
            ),
            models.Index(
                fields=[
                    "student",
                    "status",
                ],
                name="class_alloc_student_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.student.username} | "
            f"{self.section} | "
            f"{self.term} {self.academic_year}"
        )

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE