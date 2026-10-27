
from django import forms
from django.db.models import Q

from .models import Department, Program


class BootstrapModelForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():

            if isinstance(
                field.widget,
                forms.CheckboxInput,
            ):
                field.widget.attrs[
                    "class"
                ] = "form-check-input"

            else:
                field.widget.attrs[
                    "class"
                ] = "form-control"


class DepartmentForm(BootstrapModelForm):

    class Meta:
        model = Department

        fields = [
            "code",
            "name",
            "description",
            "is_active",
        ]

        widgets = {
            "code": forms.TextInput(
                attrs={
                    "placeholder": "e.g. CS",
                }
            ),
            "name": forms.TextInput(
                attrs={
                    "placeholder": (
                        "e.g. Computer Science"
                    ),
                }
            ),
            "description": forms.Textarea(
                attrs={"rows": 4}
            ),
        }

    def clean_code(self):
        return (
            self.cleaned_data["code"]
            .strip()
            .upper()
        )

    def clean_name(self):
        return self.cleaned_data["name"].strip()


class ProgramForm(BootstrapModelForm):

    class Meta:
        model = Program

        fields = [
            "department",
            "code",
            "name",
            "duration_semesters",
            "description",
            "is_active",
        ]

        widgets = {
            "code": forms.TextInput(
                attrs={
                    "placeholder": "e.g. BSCS",
                }
            ),
            "name": forms.TextInput(
                attrs={
                    "placeholder": (
                        "e.g. BS Computer Science"
                    ),
                }
            ),
            "duration_semesters": forms.NumberInput(
                attrs={
                    "min": 1,
                    "max": 12,
                }
            ),
            "description": forms.Textarea(
                attrs={"rows": 4}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        departments = Department.objects.filter(
            is_active=True
        )

        if (
            self.instance.pk
            and self.instance.department_id
        ):
            departments = Department.objects.filter(
                Q(is_active=True)
                | Q(
                    pk=self.instance.department_id
                )
            )

        self.fields["department"].queryset = (
            departments.order_by("name")
        )

    def clean_code(self):
        return (
            self.cleaned_data["code"]
            .strip()
            .upper()
        )

    def clean_name(self):
        return self.cleaned_data["name"].strip()
