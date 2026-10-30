import re

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from accounts.models import UserProfile
from courses.models import (
    CourseOffering,
    validate_academic_year,
)
from semesters.models import Section


User = get_user_model()


class ClassPeriodForm(forms.Form):

    section = forms.ModelChoiceField(
        queryset=Section.objects.none(),
        label="Program / Semester / Section",
        widget=forms.Select(
            attrs={"class": "form-select"}
        ),
    )

    academic_year = forms.CharField(
        max_length=9,
        label="Academic Year",
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


class BulkAllocationForm(ClassPeriodForm):

    usernames = forms.CharField(
        label="Student Usernames",
        help_text=(
            "Enter up to 100 student usernames. "
            "Separate them using commas or new lines."
        ),
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 8,
                "placeholder": (
                    "student001\n"
                    "student002\n"
                    "student003"
                ),
                "spellcheck": "false",
            }
        ),
    )

    allow_transfer = forms.BooleanField(
        required=False,
        label=(
            "Allow transfer from another section "
            "in the same academic year and term"
        ),
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input"}
        ),
    )

    reason = forms.CharField(
        required=False,
        max_length=200,
        label="Allocation Reason / Note",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": (
                    "Regular allocation / "
                    "Section transfer / "
                    "Semester promotion"
                ),
            }
        ),
    )

    def clean_usernames(self):
        raw = self.cleaned_data["usernames"]

        names = [
            item.strip()
            for item in re.split(r"[,;\r\n]+", raw)
            if item.strip()
        ]

        # Remove repeated usernames but preserve order.
        names = list(dict.fromkeys(names))

        if not names:
            raise ValidationError(
                "Enter at least one student username."
            )

        if len(names) > 100:
            raise ValidationError(
                "Maximum 100 students per operation."
            )

        users_by_name = {
            user.username: user
            for user in User.objects.filter(
                username__in=names
            )
        }

        missing = [
            name
            for name in names
            if name not in users_by_name
        ]

        if missing:
            raise ValidationError(
                "Unknown username(s): "
                + ", ".join(missing[:10])
            )

        users = [
            users_by_name[name]
            for name in names
        ]

        inactive = [
            user.username
            for user in users
            if not user.is_active
        ]

        if inactive:
            raise ValidationError(
                "Inactive account(s): "
                + ", ".join(inactive[:10])
            )

        valid_student_ids = set(
            UserProfile.objects.filter(
                user_id__in=[
                    user.pk for user in users
                ],
                role=UserProfile.Role.STUDENT,
            ).values_list(
                "user_id",
                flat=True,
            )
        )

        invalid_roles = [
            user.username
            for user in users
            if user.pk not in valid_student_ids
        ]

        if invalid_roles:
            raise ValidationError(
                "These accounts do not have "
                "the Student role: "
                + ", ".join(invalid_roles[:10])
            )

        self.students = users

        return raw


class AllocationFilterForm(forms.Form):

    section = forms.ModelChoiceField(
        queryset=Section.objects.all(),
        required=False,
        empty_label="All sections",
        widget=forms.Select(
            attrs={"class": "form-select"}
        ),
    )

    academic_year = forms.CharField(
        required=False,
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
        required=False,
        choices=[
            ("", "All terms"),
            *CourseOffering.Term.choices,
        ],
        widget=forms.Select(
            attrs={"class": "form-select"}
        ),
    )