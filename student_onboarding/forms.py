from django import forms

from courses.models import (
    CourseOffering,
    validate_academic_year,
)
from semesters.models import Section


class StudentImportForm(forms.Form):

    section = forms.ModelChoiceField(
        queryset=Section.objects.none(),
        label="Target Section",
        widget=forms.Select(
            attrs={"class": "form-select"}
        ),
    )

    academic_year = forms.CharField(
        max_length=9,
        validators=[validate_academic_year],
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "2026-2027",
            }
        ),
    )

    term = forms.ChoiceField(
        choices=CourseOffering.Term.choices,
        widget=forms.Select(
            attrs={"class": "form-select"}
        ),
    )

    file = forms.FileField(
        label="CSV or Excel File",
        help_text=(
            "Accepted formats: .csv and .xlsx. "
            "Maximum 500 students, 2 MB."
        ),
        widget=forms.ClearableFileInput(
            attrs={
                "class": "form-control",
                "accept": ".csv,.xlsx",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["section"].queryset = (
            Section.objects.filter(
                is_active=True,
                semester__is_active=True,
                semester__program__is_active=True,
                semester__program__department__is_active=True,
            )
            .select_related(
                "semester",
                "semester__program",
            )
            .order_by(
                "semester__program__code",
                "semester__number",
                "code",
            )
        )

    def clean_file(self):
        file = self.cleaned_data["file"]

        extension = file.name.lower().rsplit(".", 1)[-1]

        if extension not in {"csv", "xlsx"}:
            raise forms.ValidationError(
                "Only CSV and XLSX files are allowed."
            )

        if file.size > 2 * 1024 * 1024:
            raise forms.ValidationError(
                "File must not exceed 2 MB."
            )

        if file.size == 0:
            raise forms.ValidationError(
                "Uploaded file is empty."
            )

        return file