
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

    description = models.TextField(
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
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

    name = models.CharField(
        max_length=150,
    )

    duration_semesters = models.PositiveSmallIntegerField(
        default=8,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(12),
        ],
    )

    description = models.TextField(
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
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

        if not self.department_id:
            return

        try:
            department = self.department
        except Department.DoesNotExist:
            return

        if self.is_active and not department.is_active:
            raise ValidationError({
                "department": (
                    "An active program requires "
                    "an active department."
                )
            })

        if not self.pk:
            return

        existing = (
            Program.objects.filter(pk=self.pk)
            .values("department_id")
            .first()
        )

        if existing is None:
            return

        has_semesters = self.semesters.exists()

        # Existing semester records must never
        # silently move to another department.
        if (
            has_semesters
            and self.department_id
            != existing["department_id"]
        ):
            raise ValidationError({
                "department": (
                    "Cannot change the department "
                    "while this program has semesters."
                )
            })

        # Existing semester numbers must fit
        # within the program's duration.
        if (
            self.duration_semesters is not None
            and self.semesters.filter(
                number__gt=self.duration_semesters
            ).exists()
        ):
            raise ValidationError({
                "duration_semesters": (
                    "Cannot reduce program duration "
                    "below an existing semester number."
                )
            })

        # Archive children first.
        if (
            not self.is_active
            and self.semesters.filter(
                is_active=True
            ).exists()
        ):
            raise ValidationError({
                "is_active": (
                    "Archive all active semesters "
                    "before archiving this program."
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
