
from django.core.exceptions import ValidationError
from django.core.validators import (
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
)
from django.db import models
from django.db.models.functions import Lower

from departments.models import Program


section_code_validator = RegexValidator(
    regex=r"^[A-Z0-9][A-Z0-9_-]*$",
    message=(
        "Use uppercase letters, numbers, "
        "underscores or hyphens only."
    ),
)


class Semester(models.Model):
    program = models.ForeignKey(
        Program,
        on_delete=models.PROTECT,
        related_name="semesters",
    )

    number = models.PositiveSmallIntegerField(
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
            "program__department__name",
            "program__code",
            "number",
            "id",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["program", "number"],
                name="unique_semester_per_program",
            ),

            models.CheckConstraint(
                condition=(
                    models.Q(number__gte=1)
                    & models.Q(number__lte=12)
                ),
                name="semester_number_1_to_12",
            ),
        ]

    def __str__(self):
        return (
            f"{self.program.code} - "
            f"Semester {self.number}"
        )

    @property
    def display_name(self):
        return f"Semester {self.number}"

    def clean(self):
        super().clean()

        if not self.program_id:
            return

        try:
            program = self.program
        except Program.DoesNotExist:
            return

        if (
            self.number is not None
            and self.number > program.duration_semesters
        ):
            raise ValidationError({
                "number": (
                    "Semester number cannot exceed "
                    "the program duration of "
                    f"{program.duration_semesters} semesters."
                )
            })

        # Validate the complete parent hierarchy.
        if self.is_active:
            if not program.is_active:
                raise ValidationError({
                    "program": (
                        "An active semester requires "
                        "an active program."
                    )
                })

            if not program.department.is_active:
                raise ValidationError({
                    "program": (
                        "An active semester requires "
                        "an active department."
                    )
                })

        if not self.pk:
            return

        existing = (
            Semester.objects.filter(pk=self.pk)
            .values("program_id", "number")
            .first()
        )

        if existing is None:
            return

        has_sections = self.sections.exists()

        if has_sections:
            errors = {}

            if self.program_id != existing["program_id"]:
                errors["program"] = (
                    "Cannot change the program "
                    "after sections have been created."
                )

            if self.number != existing["number"]:
                errors["number"] = (
                    "Cannot change semester number "
                    "after sections have been created."
                )

            if errors:
                raise ValidationError(errors)

        if (
            not self.is_active
            and self.sections.filter(
                is_active=True
            ).exists()
        ):
            raise ValidationError({
                "is_active": (
                    "Archive all active sections "
                    "before archiving this semester."
                )
            })

        
        # Do not archive a semester while it
        # still contains active courses.
        if (
            self.pk
            and not self.is_active
            and self.courses.filter(
                is_active=True
            ).exists()
        ):
            raise ValidationError({
                "is_active": (
                    "Archive all active courses "
                    "before archiving this semester."
                )
            })

class Section(models.Model):
    semester = models.ForeignKey(
        Semester,
        on_delete=models.PROTECT,
        related_name="sections",
    )

    code = models.CharField(
        max_length=12,
        validators=[section_code_validator],
    )

    capacity = models.PositiveSmallIntegerField(
        default=40,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(500),
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
            "semester__program__code",
            "semester__number",
            "code",
            "id",
        ]

        constraints = [
            models.UniqueConstraint(
                Lower("code"),
                "semester",
                name="unique_section_code_per_semester_ci",
            ),

            models.CheckConstraint(
                condition=(
                    models.Q(capacity__gte=1)
                    & models.Q(capacity__lte=500)
                ),
                name="section_capacity_1_to_500",
            ),
        ]

    def __str__(self):
        return (
            f"{self.semester.program.code} - "
            f"Semester {self.semester.number} - "
            f"Section {self.code}"
        )

    @property
    def display_name(self):
        return f"Section {self.code}"

    def clean(self):
        super().clean()

        if not self.semester_id:
            return

        try:
            semester = self.semester
        except Semester.DoesNotExist:
            return

        # Once a section exists, its semester
        # association cannot silently change.
        if self.pk:
            existing_semester_id = (
                Section.objects.filter(pk=self.pk)
                .values_list(
                    "semester_id",
                    flat=True,
                )
                .first()
            )

            if (
                existing_semester_id is not None
                and self.semester_id
                != existing_semester_id
            ):
                raise ValidationError({
                    "semester": (
                        "Cannot move an existing "
                        "section to another semester."
                    )
                })

        if self.is_active:
            if not semester.is_active:
                raise ValidationError({
                    "semester": (
                        "An active section requires "
                        "an active semester."
                    )
                })

            if not semester.program.is_active:
                raise ValidationError({
                    "semester": (
                        "An active section requires "
                        "an active program."
                    )
                })

            if not semester.program.department.is_active:
                raise ValidationError({
                    "semester": (
                        "An active section requires "
                        "an active department."
                    )
                })
        
        # A section with active course offerings
        # cannot be archived.
        if (
            self.pk
            and not self.is_active
            and self.course_offerings.filter(
                is_active=True
            ).exists()
        ):
            raise ValidationError({
                "is_active": (
                    "Archive all active course offerings "
                    "before archiving this section."
                )
            })

    def save(self, *args, **kwargs):
        self.code = (
            self.code or ""
        ).strip().upper()

        super().save(*args, **kwargs)
