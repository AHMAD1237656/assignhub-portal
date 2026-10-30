from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from .models import UserProfile


class UserCreateForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput,
        min_length=8,
        label="Password",
    )

    role = forms.ChoiceField(
        choices=UserProfile.Role.choices,
        label="Role",
    )

    class Meta:
        model = User
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "password",
            "is_active",
        )
    def clean_password(self):
        password = self.cleaned_data["password"]

        user = User(
            username=self.cleaned_data.get("username", ""),
            first_name=self.cleaned_data.get("first_name", ""),
            last_name=self.cleaned_data.get("last_name", ""),
            email=self.cleaned_data.get("email", ""),
        )

        validate_password(password, user=user)

        return password
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field_name, field in self.fields.items():
            field.widget.attrs["class"] = "form-control"

        self.fields["is_active"].widget.attrs["class"] = "form-check-input"

    def save(self, commit=True):
        user = super().save(commit=False)

        user.set_password(self.cleaned_data["password"])

        if commit:
            user.save()

            UserProfile.objects.create(
                user=user,
                role=self.cleaned_data["role"],
            )

        return user

    
# ==========================================
# PHASE 9.1 - PROFILE EDIT FORM
# ==========================================

from django import forms
from django.contrib.auth import get_user_model


ProfileUser = get_user_model()


class SelfProfileUpdateForm(forms.ModelForm):

    class Meta:
        model = ProfileUser

        fields = [
            "first_name",
            "last_name",
            "email",
        ]

        widgets = {
            "first_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter first name",
                    "autocomplete": "given-name",
                }
            ),

            "last_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter last name",
                    "autocomplete": "family-name",
                }
            ),

            "email": forms.EmailInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter email address",
                    "autocomplete": "email",
                }
            ),
        }

    def __init__(
        self,
        *args,
        email_locked=False,
        **kwargs
    ):
        super().__init__(*args, **kwargs)

        self.email_locked = email_locked

        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        self.fields["email"].required = True

        if self.email_locked:
            self.fields["email"].disabled = True

            self.fields["email"].help_text = (
                "Student email is controlled by "
                "university administration."
            )

    def clean_first_name(self):
        value = self.cleaned_data["first_name"].strip()

        if not value:
            raise forms.ValidationError(
                "First name is required."
            )

        return value

    def clean_last_name(self):
        value = self.cleaned_data["last_name"].strip()

        if not value:
            raise forms.ValidationError(
                "Last name is required."
            )

        return value

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()

        if self.email_locked:
            return self.instance.email

        duplicate = (
            ProfileUser.objects
            .exclude(pk=self.instance.pk)
            .filter(email__iexact=email)
            .exists()
        )

        if duplicate:
            raise forms.ValidationError(
                "This email address is already in use."
            )

        return email
