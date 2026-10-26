from django import forms
from django.contrib.auth.models import User

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