
from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.validators import validate_email

from semesters.models import Section

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
