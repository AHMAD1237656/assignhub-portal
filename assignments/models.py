
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone


ASSIGNMENT_ATTACHMENT_EXTENSIONS = [
    "pdf",
    "docx",
    "doc",
    "txt",
    "pptx",
    "ppt",
    "xlsx",
    "xls",
    "csv",
    "zip",
    "rar",
]


class Assignment(models.Model):

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"
        CLOSED = "CLOSED", "Closed"

    course_offering = models.ForeignKey(
        "courses.CourseOffering",
        on_delete=models.PROTECT,
        related_name="assignments",
        null=True,
        blank=True,
    )

    title = models.CharField(max_length=255)
    instructions = models.TextField()

    attachment = models.FileField(
        upload_to="assignments/attachments/",
        blank=True,
        null=True,
        validators=[
            FileExtensionValidator(
                allowed_extensions=ASSIGNMENT_ATTACHMENT_EXTENSIONS,
                message=(
                    "Allowed file types: .pdf, .docx, .doc, .txt, "
                    ".pptx, .ppt, .xlsx, .xls, .csv, .zip, .rar."
                ),
            )
        ],
    )

    deadline = models.DateTimeField()

    total_marks = models.PositiveIntegerField(default=100)

    rubric = models.TextField(blank=True)

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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        errors = {}

        if (
            self.total_marks is not None
            and self.total_marks < 1
        ):
            errors["total_marks"] = (
                "Total marks must be at least 1."
            )

        if self.deadline is None:
            errors["deadline"] = "Deadline is required."

        else:
            now = timezone.now()

            if self.pk is None:
                # Newly created assignments need
                # a future submission deadline.
                if self.deadline <= now:
                    errors["deadline"] = (
                        "Deadline must be in the future."
                    )

            else:
                previous_deadline = (
                    Assignment.objects.filter(
                        pk=self.pk
                    )
                    .values_list(
                        "deadline",
                        flat=True,
                    )
                    .first()
                )

                if (
                    previous_deadline is not None
                    and self.deadline != previous_deadline
                    and self.deadline <= now
                ):
                    errors["deadline"] = (
                        "Cannot change the deadline "
                        "to a past date or time."
                    )
        if (
            self.status == self.Status.PUBLISHED
            and not self.course_offering_id
        ):
            errors["course_offering"] = (
                "Select a Course Offering before publishing."
            )

        if self.course_offering_id:
            offering = self.course_offering

            if (
                self.created_by_id
                and offering.teacher_id != self.created_by_id
            ):
                errors["course_offering"] = (
                    "Assignment teacher must match "
                    "the Course Offering teacher."
                )

            if (
                self.status == self.Status.PUBLISHED
                and not all([
                    offering.is_active,
                    offering.course.is_active,
                    offering.section.is_active,
                    offering.course.semester.is_active,
                    offering.course.program.is_active,
                    offering.course.program.department.is_active,
                ])
            ):
                errors["course_offering"] = (
                    "Cannot publish under an "
                    "inactive Course Offering."
                )

        if self.pk:
            previous = (
                Assignment.objects.filter(pk=self.pk)
                .values("course_offering_id")
                .first()
            )

            if (
                previous
                and self.submissions.exists()
                and self.course_offering_id
                != previous["course_offering_id"]
            ):
                errors["course_offering"] = (
                    "Cannot change Course Offering "
                    "after submissions exist."
                )

        if errors:
            raise ValidationError(errors)

    @property
    def is_overdue(self):
        return bool(
            self.deadline
            and timezone.now() > self.deadline
        )

    @property
    def is_open(self):
        return (
            self.status == self.Status.PUBLISHED
            and not self.is_overdue
            and self.deadline is not None
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

    text_content = models.TextField(blank=True)

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

    feedback = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "student"],
                name="unique_assignment_student_submission",
            )
        ]

    def __str__(self):
        return (
            f"{self.student.username} "
            f"- {self.assignment.title}"
        )

    def clean(self):
        super().clean()
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
                    "Finalized submissions need "
                    "a submission timestamp."
                )

            if not (
                (self.text_content or "").strip()
                or self.submission_file
            ):
                errors["text_content"] = (
                    "Provide text or a PDF."
                )

        if errors:
            raise ValidationError(errors)
