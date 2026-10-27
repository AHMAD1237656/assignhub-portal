
from pathlib import Path

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile

from .models import Assignment, Submission


# =====================================================
# FILE UPLOAD CONFIGURATION
# =====================================================

MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MB


# =====================================================
# PDF VALIDATION
# =====================================================

def validate_pdf(file):
    """
    Validate an uploaded PDF.

    Checks:
    - PDF extension
    - Non-empty file
    - Maximum file size: 10 MB
    - PDF file signature

    Existing stored files are not re-read during editing.
    """

    if not file:
        return file

    filename = Path(file.name).name

    if Path(filename).suffix.lower() != ".pdf":
        raise ValidationError(
            "Only PDF files are allowed."
        )

    if file.size == 0:
        raise ValidationError(
            "The PDF file cannot be empty."
        )

    if file.size > MAX_PDF_BYTES:
        raise ValidationError(
            "PDF size must not exceed 10 MB."
        )

    # Only inspect newly uploaded files.
    if not isinstance(file, UploadedFile):
        return file

    original_position = file.tell()

    try:
        file.seek(0)

        header = file.read(5)

        if header != b"%PDF-":
            raise ValidationError(
                "Invalid PDF file signature."
            )

    finally:
        file.seek(original_position)

    return file


# =====================================================
# ASSIGNMENT CREATE / EDIT FORM
# =====================================================

class AssignmentForm(forms.ModelForm):

    class Meta:
        model = Assignment

        fields = (
            "title",
            "instructions",
            "attachment",
            "deadline",
            "total_marks",
            "rubric",
            "status",
        )

        widgets = {
            "title": forms.TextInput(
                attrs={
                    "placeholder": "Enter assignment title",
                }
            ),

            "instructions": forms.Textarea(
                attrs={
                    "rows": 6,
                    "placeholder": "Enter assignment instructions",
                }
            ),

            "deadline": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                },
                format="%Y-%m-%dT%H:%M",
            ),

            "total_marks": forms.NumberInput(
                attrs={
                    "min": "1",
                    "step": "1",
                }
            ),

            "rubric": forms.Textarea(
                attrs={
                    "rows": 5,
                    "placeholder": "Optional grading rubric",
                }
            ),

            "attachment": forms.ClearableFileInput(
                attrs={
                    "accept": ".pdf,application/pdf",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["deadline"].input_formats = [
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M:%S",
        ]

        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

    def clean_attachment(self):
        attachment = self.cleaned_data.get("attachment")

        return validate_pdf(attachment)

    def clean_total_marks(self):
        total_marks = self.cleaned_data.get("total_marks")

        if total_marks is None or total_marks < 1:
            raise ValidationError(
                "Total marks must be at least 1."
            )

        return total_marks


# =====================================================
# STUDENT SUBMISSION FORM
# =====================================================

class SubmissionForm(forms.ModelForm):

    class Meta:
        model = Submission

        fields = (
            "text_content",
            "submission_file",
        )

        widgets = {
            "text_content": forms.Textarea(
                attrs={
                    "rows": 12,
                    "placeholder": "Write your assignment answer here...",
                }
            ),

            "submission_file": forms.ClearableFileInput(
                attrs={
                    "accept": ".pdf,application/pdf",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

    def clean_submission_file(self):
        submission_file = self.cleaned_data.get(
            "submission_file"
        )

        return validate_pdf(submission_file)

    def clean(self):
        cleaned_data = super().clean()

        text_content = (
            cleaned_data.get("text_content") or ""
        ).strip()

        submission_file = cleaned_data.get(
            "submission_file"
        )

        if not text_content and not submission_file:
            raise ValidationError(
                "Write an answer or upload a PDF file."
            )

        return cleaned_data


# =====================================================
# TEACHER GRADING FORM
# =====================================================

class GradeSubmissionForm(forms.ModelForm):

    class Meta:
        model = Submission

        fields = (
            "marks",
            "feedback",
        )

        widgets = {
            "marks": forms.NumberInput(
                attrs={
                    "min": "0",
                    "step": "0.01",
                    "placeholder": "Enter obtained marks",
                }
            ),

            "feedback": forms.Textarea(
                attrs={
                    "rows": 6,
                    "placeholder": "Enter feedback for student",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

        # Marks must be explicitly provided on every grading POST.
        self.fields["marks"].required = True

        # Do not reuse an existing grade if the POST omits marks.
        if self.is_bound:
            self.fields["marks"].initial = None

    def clean_marks(self):
        marks = self.cleaned_data.get("marks")

        if marks is None:
            raise ValidationError(
                "Marks are required."
            )

        total_marks = self.instance.assignment.total_marks

        if marks < 0 or marks > total_marks:
            raise ValidationError(
                f"Marks must be between 0 and {total_marks}."
            )

        return marks
