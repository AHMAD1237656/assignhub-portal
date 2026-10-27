
from django.core.exceptions import ValidationError
from django.core.validators import (
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
)
from django.db import models
from django.db.models.functions import Lower


code_validator = RegexValidator(
    regex=r"^[A-Z0-9][A-Z0-9_-]*$",
    message=(
        "Use letters A-Z, numbers, hyphens, "
        "or underscores. No spaces."
    ),
)


class Department(models.Model):
    code = models.CharField(
        max_length=20,
        validators=[code_validator],
    )

    name = models.CharField(max_length=150)

    description = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = ["name", "id"]

        constraints = [
            models.UniqueConstraint(
                Lower("code"),
                name="unique_department_code_ci",
            ),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"

    def clean(self):
        super().clean()

        if (
            self.pk
            and not self.is_active
            and self.programs.filter(
                is_active=True
            ).exists()
        ):
            raise ValidationError({
                "is_active": (
                    "Archive all active programs "
                    "before archiving this department."
                )
            })

    def save(self, *args, **kwargs):
        self.code = (
            self.code or ""
        ).strip().upper()

        self.name = (
            self.name or ""
        ).strip()

        super().save(*args, **kwargs)


class Program(models.Model):
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="programs",
    )

    code = models.CharField(
        max_length=20,
        validators=[code_validator],
    )

    name = models.CharField(max_length=150)

    duration_semesters = models.PositiveSmallIntegerField(
        default=8,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(12),
        ],
    )

    description = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = [
            "department__name",
            "code",
            "id",
        ]

        constraints = [
            models.UniqueConstraint(
                Lower("code"),
                "department",
                name="unique_program_code_per_dept_ci",
            ),

            # Database-level validation.
            models.CheckConstraint(
                condition=(
                    models.Q(duration_semesters__gte=1)
                    & models.Q(duration_semesters__lte=12)
                ),
                name="program_duration_1_to_12",
            ),
        ]

    def __str__(self):
        return (
            f"{self.code} - {self.name} "
            f"({self.department.code})"
        )

    def clean(self):
        super().clean()

        if (
            self.department_id
            and self.is_active
            and not self.department.is_active
        ):
            raise ValidationError({
                "department": (
                    "An active program requires "
                    "an active department."
                )
            })

    def save(self, *args, **kwargs):
        self.code = (
            self.code or ""
        ).strip().upper()

        self.name = (
            self.name or ""
        ).strip()

        super().save(*args, **kwargs)
