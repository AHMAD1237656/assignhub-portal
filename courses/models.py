
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import (
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
)
from django.db import models
from django.db.models.functions import Lower

from accounts.models import UserProfile
from departments.models import Program
from semesters.models import Section, Semester


course_code_validator = RegexValidator(
    regex=r"^[A-Z0-9][A-Z0-9_-]*$",
    message="Use uppercase letters, numbers, '-' or '_'.",
)


def validate_academic_year(value):
    if not re.fullmatch(r"[0-9]{4}-[0-9]{4}", value or ""):
        raise ValidationError(
            "Use YYYY-YYYY, e.g. 2026-2027."
        )

    start, end = map(int, value.split("-"))

    if end != start + 1:
        raise ValidationError(
            "Academic year must contain consecutive years."
        )

    if start < 2000 or start > 9998:
        raise ValidationError(
            "Academic year is outside the allowed range."
        )


class Course(models.Model):

    program = models.ForeignKey(
        Program,
        on_delete=models.PROTECT,
        related_name="courses",
    )

    semester = models.ForeignKey(
        Semester,
        on_delete=models.PROTECT,
        related_name="courses",
    )

    code = models.CharField(
        max_length=20,
        validators=[course_code_validator],
    )

    title = models.CharField(max_length=200)

    credit_hours = models.PositiveSmallIntegerField(
        default=3,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(6),
        ],
    )

    description = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "program__code",
            "semester__number",
            "code",
            "pk",
        ]

        constraints = [
            models.UniqueConstraint(
                Lower("code"),
                "program",
                name="course_code_program_ci",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(credit_hours__gte=1)
                    & models.Q(credit_hours__lte=6)
                ),
                name="course_credit_hours_1_6",
            ),
        ]

    def __str__(self):
        return f"{self.code} - {self.title}"

    def clean(self):
        super().clean()
        errors = {}

        if not self.program_id or not self.semester_id:
            return

        try:
            program = self.program
            semester = self.semester
        except (Program.DoesNotExist, Semester.DoesNotExist):
            return

        if semester.program_id != self.program_id:
            errors["semester"] = (
                "Semester must belong to the selected program."
            )

        if self.is_active and (
            not program.is_active
            or not program.department.is_active
            or not semester.is_active
        ):
            errors["is_active"] = (
                "Program, department and semester "
                "must be active."
            )

        if self.pk:
            previous = (
                Course.objects.filter(pk=self.pk)
                .values("program_id", "semester_id")
                .first()
            )

            if previous and self.offerings.exists():
                if self.program_id != previous["program_id"]:
                    errors["program"] = (
                        "Cannot change program after "
                        "course offerings exist."
                    )

                if self.semester_id != previous["semester_id"]:
                    errors["semester"] = (
                        "Cannot change semester after "
                        "course offerings exist."
                    )

            if (
                not self.is_active
                and self.offerings.filter(
                    is_active=True
                ).exists()
            ):
                errors["is_active"] = (
                    "Archive active course offerings first."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper()
        self.title = (self.title or "").strip()
        super().save(*args, **kwargs)


class CourseOffering(models.Model):

    class Term(models.TextChoices):
        SPRING = "SPRING", "Spring"
        SUMMER = "SUMMER", "Summer"
        FALL = "FALL", "Fall"

    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        related_name="offerings",
    )

    section = models.ForeignKey(
        Section,
        on_delete=models.PROTECT,
        related_name="course_offerings",
    )

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="teaching_offerings",
    )

    academic_year = models.CharField(
        max_length=9,
        validators=[validate_academic_year],
        help_text="Example: 2026-2027",
    )

    term = models.CharField(
        max_length=10,
        choices=Term.choices,
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "-academic_year",
            "term",
            "course__code",
            "section__code",
            "pk",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "course",
                    "section",
                    "academic_year",
                    "term",
                ],
                name="unique_course_section_term_year",
            )
        ]

        indexes = [
            models.Index(
                fields=["teacher", "is_active"],
                name="offering_teacher_active_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.course.code} / "
            f"Semester {self.section.semester.number} / "
            f"Section {self.section.code} / "
            f"{self.term.title()} {self.academic_year}"
        )

    def clean(self):
        super().clean()

        errors = {}

        try:
            validate_academic_year(self.academic_year)
        except ValidationError as exc:
            errors["academic_year"] = exc.messages

        if not all([
            self.course_id,
            self.section_id,
            self.teacher_id,
        ]):
            if errors:
                raise ValidationError(errors)
            return

        try:
            course = self.course
            section = self.section
            teacher = self.teacher
        except (
            Course.DoesNotExist,
            Section.DoesNotExist,
            self._meta.get_field("teacher").remote_field.model.DoesNotExist,
        ):
            return

        if course.semester_id != section.semester_id:
            errors["section"] = (
                "Section must belong to the "
                "course's semester."
            )

        if not teacher.is_active:
            errors["teacher"] = "Teacher account must be active."

        elif not UserProfile.objects.filter(
            user_id=teacher.pk,
            role=UserProfile.Role.TEACHER,
        ).exists():
            errors["teacher"] = (
                "Selected user must have the Teacher role."
            )

        if self.is_active and not all([
            course.is_active,
            course.program.is_active,
            course.program.department.is_active,
            course.semester.is_active,
            section.is_active,
        ]):
            errors["is_active"] = (
                "Course and its academic hierarchy "
                "must be active."
            )

        if self.pk:
            previous = (
                CourseOffering.objects.filter(pk=self.pk)
                .values(
                    "course_id",
                    "section_id",
                    "teacher_id",
                    "academic_year",
                    "term",
                )
                .first()
            )
            if (
                not self.is_active
                and self.enrollments.filter(
                    status="ACTIVE"
                ).exists()
            ):
                errors["is_active"] = (
                    "Drop active enrollments "
                    "before archiving this offering."
                )        

            if previous and self.enrollments.exists():
                for field in (
                    "course_id",
                    "section_id",
                    "teacher_id",
                    "academic_year",
                    "term",
                ):
                    if getattr(self, field) != previous[field]:
                        form_field = (
                            field[:-3]
                            if field.endswith("_id")
                            else field
                        )
                        errors[form_field] = (
                            "Cannot change this value "
                            "after enrollments exist."
                        )

            # Assignment link is introduced in the
            # Assignments integration section below.
            if hasattr(self, "assignments"):
                if (
                    not self.is_active
                    and self.assignments.filter(
                        status="PUBLISHED"
                    ).exists()
                ):
                    errors["is_active"] = (
                        "Close published assignments "
                        "before archiving this offering."
                    )

                if previous and self.assignments.exists():
                    for field in (
                        "course_id",
                        "section_id",
                        "teacher_id",
                        "academic_year",
                        "term",
                    ):
                        if getattr(self, field) != previous[field]:
                            form_field = (
                                field[:-3]
                                if field.endswith("_id")
                                else field
                            )
                            errors[form_field] = (
                                "Cannot change this value "
                                "after assignments exist."
                            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.academic_year = (
            self.academic_year or ""
        ).strip()

        super().save(*args, **kwargs)


class CourseEnrollment(models.Model):

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        DROPPED = "DROPPED", "Dropped"

    offering = models.ForeignKey(
        CourseOffering,
        on_delete=models.PROTECT,
        related_name="enrollments",
    )

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="course_enrollments",
    )

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    enrolled_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-enrolled_at", "-pk"]

        constraints = [
            models.UniqueConstraint(
                fields=["offering", "student"],
                name="unique_student_course_offering",
            ),
        ]

    def __str__(self):
        return (
            f"{self.student.username} / "
            f"{self.offering.course.code}"
        )

    def clean(self):
        super().clean()
        errors = {}

        if not self.student_id or not self.offering_id:
            return

        try:
            student = self.student
            offering = self.offering
        except Exception as exc:
            # Do not hide unrelated programming errors.
            if isinstance(
                exc,
                self._meta.get_field(
                    "student"
                ).remote_field.model.DoesNotExist,
            ) or isinstance(exc, CourseOffering.DoesNotExist):
                return
            raise

        if not student.is_active:
            errors["student"] = "Student account is inactive."

        elif not UserProfile.objects.filter(
            user_id=student.pk,
            role=UserProfile.Role.STUDENT,
        ).exists():
            errors["student"] = (
                "Selected user must have the Student role."
            )

        if (
            self.status == self.Status.ACTIVE
            and not offering.is_active
        ):
            errors["offering"] = (
                "Cannot activate enrollment "
                "in an archived offering."
            )

        if self.pk:
            previous = (
                CourseEnrollment.objects.filter(pk=self.pk)
                .values("student_id", "offering_id")
                .first()
            )

            if previous:
                if self.student_id != previous["student_id"]:
                    errors["student"] = (
                        "Student cannot be changed."
                    )

                if self.offering_id != previous["offering_id"]:
                    errors["offering"] = (
                        "Offering cannot be changed."
                    )
        if (
            self.status == self.Status.ACTIVE
            and self.student_id
            and self.offering_id
        ):
            duplicates = CourseEnrollment.objects.filter(
                student_id=self.student_id,
                status=self.Status.ACTIVE,
                offering__course_id=offering.course_id,
                offering__academic_year=offering.academic_year,
                offering__term=offering.term,
            )

            if self.pk:
                duplicates = duplicates.exclude(pk=self.pk)

            if duplicates.exists():
                errors["offering"] = (
                    "Student already has an active "
                    "enrollment in another section "
                    "of this course and term."
                )
        if errors:
            raise ValidationError(errors)
