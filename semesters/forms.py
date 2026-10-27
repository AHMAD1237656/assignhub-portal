
from django import forms
from django.db.models import Q

from departments.models import Program
from .models import Section, Semester


class StyledModelForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            if isinstance(
                field.widget,
                forms.CheckboxInput,
            ):
                css_class = "form-check-input"

            elif isinstance(
                field.widget,
                forms.Select,
            ):
                css_class = "form-select"

            else:
                css_class = "form-control"

            field.widget.attrs["class"] = css_class


class SemesterForm(StyledModelForm):

    class Meta:
        model = Semester

        fields = [
            "program",
            "number",
            "description",
            "is_active",
        ]

        widgets = {
            "number": forms.NumberInput(
                attrs={"min": 1, "max": 12}
            ),
            "description": forms.Textarea(
                attrs={"rows": 3}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        queryset = Program.objects.filter(
            is_active=True,
            department__is_active=True,
        )

        if self.instance.pk:
            queryset = Program.objects.filter(
                Q(
                    is_active=True,
                    department__is_active=True,
                )
                | Q(pk=self.instance.program_id)
            )

        self.fields["program"].queryset = (
            queryset.select_related(
                "department"
            ).order_by(
                "department__name",
                "code",
            )
        )


class SectionForm(StyledModelForm):

    class Meta:
        model = Section

        fields = [
            "semester",
            "code",
            "capacity",
            "description",
            "is_active",
        ]

        widgets = {
            "code": forms.TextInput(
                attrs={"placeholder": "e.g. A"}
            ),
            "capacity": forms.NumberInput(
                attrs={"min": 1, "max": 500}
            ),
            "description": forms.Textarea(
                attrs={"rows": 3}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        queryset = Semester.objects.filter(
            is_active=True,
            program__is_active=True,
            program__department__is_active=True,
        )

        if self.instance.pk:
            queryset = Semester.objects.filter(
                Q(
                    is_active=True,
                    program__is_active=True,
                    program__department__is_active=True,
                )
                | Q(pk=self.instance.semester_id)
            )

        self.fields["semester"].queryset = (
            queryset.select_related(
                "program"
            ).order_by(
                "program__code",
                "number",
            )
        )

    def clean_code(self):
        return (
            self.cleaned_data["code"]
            .strip()
            .upper()
        )
