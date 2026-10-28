
from pathlib import Path
from django.utils import timezone
from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile

from courses.models import CourseOffering

from .models import Assignment, Submission


MAX_PDF_BYTES = 10 * 1024 * 1024


def validate_pdf(file):
    if not file:
        return file

    filename = Path(file.name).name

    if Path(filename).suffix.lower() != ".pdf":
        raise ValidationError(
            "Only PDF files are allowed."
        )

    if file.size == 0:
        raise ValidationError(
            "PDF file cannot be empty."
        )

    if file.size > MAX_PDF_BYTES:
        raise ValidationError(
            "PDF must not exceed 10 MB."
        )

    if not isinstance(file, UploadedFile):
        return file

    position = file.tell()

    try:
        file.seek(0)

        if file.read(5) != b"%PDF-":
            raise ValidationError(
                "Invalid PDF file signature."
            )

    finally:
        file.seek(position)

    return file


class AssignmentForm(forms.ModelForm):

    class Meta:
        model = Assignment

        fields = [
            "course_offering",
            "title",
            "instructions",
            "attachment",
            "deadline",
            "total_marks",
            "rubric",
            "status",
        ]

        widgets = {
            "instructions": forms.Textarea(
                attrs={"rows": 6}
            ),
            "rubric": forms.Textarea(
                attrs={"rows": 5}
            ),
            "deadline": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["deadline"].input_formats = [
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
        ]

        offerings = CourseOffering.objects.none()

        if user is not None and user.is_authenticated:
            offerings = CourseOffering.objects.filter(
                teacher=user,
                is_active=True,
                course__is_active=True,
                section__is_active=True,
            )

            if self.instance.pk:
                offerings = CourseOffering.objects.filter(
                    models_Q_for_existing(
                        offerings,
                        self.instance.course_offering_id,
                    )
                )

        self.fields[
            "course_offering"
        ].queryset = offerings.select_related(
            "course",
            "section",
        )

        self.fields[
            "course_offering"
        ].required = False

        for field in self.fields.values():
            if isinstance(
                field.widget,
                forms.Select,
            ):
                field.widget.attrs["class"] = "form-select"
            else:
                field.widget.attrs["class"] = "form-control"

    def clean_attachment(self):
        return validate_pdf(
            self.cleaned_data.get("attachment")
        )

    def clean_total_marks(self):
        marks = self.cleaned_data["total_marks"]

        if marks < 1:
            raise ValidationError(
                "Total marks must be at least 1."
            )

        return marks
    def clean_deadline(self):
        deadline = self.cleaned_data.get("deadline")

        if deadline is None:
            return deadline

        now = timezone.now()

        # New assignment must have a future deadline.
        if not self.instance.pk and deadline <= now:
            raise ValidationError(
                "Deadline must be in the future. "
                "Please select a later date and time."
            )

        # Editing an assignment must not allow
        # setting an already-expired deadline.
        if self.instance.pk:
            original_deadline = (
                Assignment.objects.filter(
                    pk=self.instance.pk
                )
                .values_list(
                    "deadline",
                    flat=True,
                )
                .first()
            )

            if (
                deadline != original_deadline
                and deadline <= now
            ):
                raise ValidationError(
                    "Cannot change the deadline "
                    "to a past date or time."
                )

        return deadline


def models_Q_for_existing(queryset, existing_id):
    from django.db.models import Q

    return (
        Q(pk__in=queryset.values("pk"))
        | Q(pk=existing_id)
    )


class SubmissionForm(forms.ModelForm):

    class Meta:
        model = Submission

        fields = [
            "text_content",
            "submission_file",
        ]

        widgets = {
            "text_content": forms.Textarea(
                attrs={
                    "rows": 12,
                    "class": "form-control",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields[
            "submission_file"
        ].widget.attrs["class"] = "form-control"

    def clean_submission_file(self):
        return validate_pdf(
            self.cleaned_data.get("submission_file")
        )

    def clean(self):
        data = super().clean()

        text = (
            data.get("text_content") or ""
        ).strip()

        uploaded_file = data.get("submission_file")

        if not text and not uploaded_file:
            raise ValidationError(
                "Provide text or upload a PDF."
            )

        return data


class GradeSubmissionForm(forms.ModelForm):

    class Meta:
        model = Submission

        fields = ["marks", "feedback"]

        widgets = {
            "marks": forms.NumberInput(
                attrs={
                    "min": 0,
                    "step": "0.01",
                }
            ),
            "feedback": forms.Textarea(
                attrs={"rows": 6}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["marks"].required = True

        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

    def clean_marks(self):
        key = self.add_prefix("marks")

        if self.is_bound and not str(
            self.data.get(key, "")
        ).strip():
            raise ValidationError(
                "Marks are required."
            )

        marks = self.cleaned_data.get("marks")

        if marks is None:
            raise ValidationError(
                "Marks are required."
            )

        if marks < 0:
            raise ValidationError(
                "Marks cannot be negative."
            )

        if marks > self.instance.assignment.total_marks:
            raise ValidationError(
                "Marks cannot exceed total marks."
            )

        return marks
