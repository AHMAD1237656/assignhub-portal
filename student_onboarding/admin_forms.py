
from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.validators import validate_email

from semesters.models import Section
from departments.models import Department, Program

from courses.models import (
    CourseOffering,
    validate_academic_year,
)
from .models import StudentIdentity


User = get_user_model()


class StudentDirectoryFilterForm(forms.Form):

    q = forms.CharField(
        required=False,
        max_length=100,
        label="Search",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": (
                    "Roll number, name or email"
                ),
            }
        ),
    )

    status = forms.ChoiceField(
        required=False,
        choices=[
            ("", "All account statuses"),
            *StudentIdentity.Status.choices,
        ],
        widget=forms.Select(
            attrs={"class": "form-select"}
        ),
    )

    email_status = forms.ChoiceField(
        required=False,
        choices=[
            ("", "All email statuses"),
            *StudentIdentity.EmailStatus.choices,
        ],
        widget=forms.Select(
            attrs={"class": "form-select"}
        ),
    )

    section = forms.ModelChoiceField(
        queryset=Section.objects.all(),
        required=False,
        empty_label="All sections",
        widget=forms.Select(
            attrs={"class": "form-select"}
        ),
    )


class PendingStudentEditForm(forms.Form):

    first_name = forms.CharField(
        max_length=150,
        min_length=1,
        widget=forms.TextInput(
            attrs={"class": "form-control"}
        ),
    )

    last_name = forms.CharField(
        max_length=150,
        min_length=1,
        widget=forms.TextInput(
            attrs={"class": "form-control"}
        ),
    )

    email = forms.EmailField(
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
                "autocomplete": "off",
            }
        ),
    )

    def __init__(self, *args, identity=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.identity = identity

        if identity is not None and not self.is_bound:
            self.initial.update({
                "first_name": identity.user.first_name,
                "last_name": identity.user.last_name,
                "email": identity.institutional_email,
            })

    def clean_first_name(self):
        return self._clean_name(
            self.cleaned_data["first_name"]
        )

    def clean_last_name(self):
        return self._clean_name(
            self.cleaned_data["last_name"]
        )

    @staticmethod
    def _clean_name(value):
        value = value.strip()

        if any(ord(char) < 32 for char in value):
            raise forms.ValidationError(
                "Control characters are not allowed."
            )

        if value.startswith(("=", "+", "-", "@")):
            raise forms.ValidationError(
                "Invalid name format."
            )

        return value

    def clean_email(self):
        email = (
            self.cleaned_data["email"]
            .strip()
            .lower()
        )

        validate_email(email)

        required_domain = getattr(
            settings,
            "STUDENT_EMAIL_DOMAIN",
            "",
        ).strip().lower()

        if (
            required_domain
            and email.rsplit("@", 1)[-1] != required_domain
        ):
            raise forms.ValidationError(
                "Use the configured university email domain."
            )

        current_user_id = (
            self.identity.user_id
            if self.identity is not None
            else None
        )

        if (
            User.objects
            .exclude(pk=current_user_id)
            .filter(email__iexact=email)
            .exists()
        ):
            raise forms.ValidationError(
                "This email is already used by another account."
            )

        identity_qs = (
            StudentIdentity.objects
            .filter(institutional_email__iexact=email)
        )

        if self.identity is not None:
            identity_qs = identity_qs.exclude(
                pk=self.identity.pk
            )

        if identity_qs.exists():
            raise forms.ValidationError(
                "This student email already exists."
            )

        return email


class CancelPendingStudentForm(forms.Form):

    reason = forms.CharField(
        min_length=8,
        max_length=200,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": (
                    "Explain why this account "
                    "should be cancelled."
                ),
            }
        ),
    )

    confirm = forms.BooleanField(
        required=True,
        label="I confirm this cancellation.",
    )


class ManualStudentCreateForm(forms.Form):

    # -----------------------------
    # Academic Placement
    # -----------------------------

    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        label="Department",
        empty_label="Select Department",
        widget=forms.Select(
            attrs={"class": "form-select"}
        ),
    )

    program = forms.ModelChoiceField(
        queryset=Program.objects.none(),
        label="Program",
        empty_label="Select Program",
        widget=forms.Select(
            attrs={"class": "form-select"}
        ),
    )

    academic_year = forms.CharField(
        max_length=9,
        validators=[validate_academic_year],
        label="Academic Year",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "2026-2027",
                "autocomplete": "off",
            }
        ),
    )

    section = forms.ModelChoiceField(
        queryset=Section.objects.none(),
        label="Academic Section",
        empty_label="Select Section",
        widget=forms.Select(
            attrs={"class": "form-select"}
        ),
    )

    # -----------------------------
    # Student Information
    # -----------------------------

    roll_number = forms.CharField(
        max_length=40,
        min_length=3,
        label="Roll Number",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "e.g. FA21-BSE-001",
                "autocomplete": "off",
            }
        ),
    )

    first_name = forms.CharField(
        max_length=150,
        min_length=1,
        label="First Name",
        widget=forms.TextInput(
            attrs={"class": "form-control"}
        ),
    )

    last_name = forms.CharField(
        max_length=150,
        min_length=1,
        label="Last Name",
        widget=forms.TextInput(
            attrs={"class": "form-control"}
        ),
    )

    email = forms.EmailField(
        max_length=254,
        label="Institutional Email",
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
                "autocomplete": "off",
            }
        ),
    )

    term = forms.ChoiceField(
        choices=CourseOffering.Term.choices,
        label="Term",
        widget=forms.Select(
            attrs={"class": "form-select"}
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["department"].queryset = (
            Department.objects.filter(
                is_active=True
            ).order_by("name")
        )

        department_id = self.data.get(
            self.add_prefix("department")
        )

        program_id = self.data.get(
            self.add_prefix("program")
        )

        if department_id and str(department_id).isdigit():
            self.fields["program"].queryset = (
                Program.objects.filter(
                    department_id=department_id,
                    department__is_active=True,
                    is_active=True,
                )
                .select_related("department")
                .order_by("code")
            )

        if program_id and str(program_id).isdigit():
            self.fields["section"].queryset = (
                Section.objects.filter(
                    semester__program_id=program_id,
                    is_active=True,
                    semester__is_active=True,
                    semester__program__is_active=True,
                    semester__program__department__is_active=True,
                )
                .select_related(
                    "semester",
                    "semester__program",
                    "semester__program__department",
                )
                .order_by(
                    "semester__number",
                    "code",
                )
            )

    def clean_roll_number(self):
        roll_number = (
            self.cleaned_data["roll_number"]
            .strip()
            .upper()
        )

        import re

        if not re.fullmatch(
            r"[A-Z0-9][A-Z0-9_-]{2,39}",
            roll_number,
        ):
            raise forms.ValidationError(
                "Invalid roll number format."
            )

        return roll_number

    def clean_first_name(self):
        return self._clean_name(
            self.cleaned_data["first_name"]
        )

    def clean_last_name(self):
        return self._clean_name(
            self.cleaned_data["last_name"]
        )

    @staticmethod
    def _clean_name(value):
        value = value.strip()

        if not value:
            raise forms.ValidationError(
                "This field is required."
            )

        if value.startswith(("=", "+", "-", "@")):
            raise forms.ValidationError(
                "Invalid name format."
            )

        if any(ord(char) < 32 for char in value):
            raise forms.ValidationError(
                "Control characters are not allowed."
            )

        return value

    def clean_email(self):
        email = (
            self.cleaned_data["email"]
            .strip()
            .lower()
        )

        required_domain = getattr(
            settings,
            "STUDENT_EMAIL_DOMAIN",
            "",
        ).strip().lower()

        if (
            required_domain
            and email.rsplit("@", 1)[-1] != required_domain
        ):
            raise forms.ValidationError(
                "Use the configured university email domain."
            )

        if User.objects.filter(
            email__iexact=email
        ).exists():
            raise forms.ValidationError(
                "This email is already used by another account."
            )

        if StudentIdentity.objects.filter(
            institutional_email__iexact=email
        ).exists():
            raise forms.ValidationError(
                "This student email already exists."
            )

        return email

    def clean(self):
        cleaned_data = super().clean()

        department = cleaned_data.get("department")
        program = cleaned_data.get("program")
        section = cleaned_data.get("section")
        roll_number = cleaned_data.get("roll_number")

        # Verify complete academic hierarchy.
        if department and program:
            if program.department_id != department.pk:
                self.add_error(
                    "program",
                    "Selected program does not belong to this department.",
                )

        if program and section:
            if section.semester.program_id != program.pk:
                self.add_error(
                    "section",
                    "Selected section does not belong to this program.",
                )

        if roll_number and User.objects.filter(
            username__iexact=roll_number
        ).exists():
            self.add_error(
                "roll_number",
                "An account with this roll number already exists.",
            )

        return cleaned_data
