
from django import forms
from django.db.models import Q

from departments.models import Department, Program
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

    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        required=True,
        label="Department",
        empty_label="Select Department",
    )

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

        self.order_fields([
            "department",
            "program",
            "number",
            "description",
            "is_active",
        ])

        current_program_id = (
            self.instance.program_id
            if self.instance.pk
            else None
        )

        current_department_id = (
            self.instance.program.department_id
            if self.instance.pk
            else None
        )

        # Determine selected department.
        if self.is_bound:
            department_id = self.data.get(
                self.add_prefix("department")
            )
        else:
            department_id = (
                self.initial.get("department")
                or current_department_id
            )

        department_queryset = Department.objects.filter(
            is_active=True
        )

        # Preserve the existing department when editing,
        # even if it has subsequently been archived.
        if current_department_id:
            department_queryset = (
                department_queryset
                | Department.objects.filter(
                    pk=current_department_id
                )
            )

        self.fields["department"].queryset = (
            department_queryset.order_by("name")
        )

        # Only show programs belonging to selected department.
        program_queryset = Program.objects.none()

        if department_id:
            program_queryset = Program.objects.filter(
                department_id=department_id,
                is_active=True,
                department__is_active=True,
            )

            # Preserve the existing program during editing.
            if (
                current_program_id
                and str(department_id)
                == str(current_department_id)
            ):
                program_queryset = (
                    program_queryset
                    | Program.objects.filter(
                        pk=current_program_id,
                        department_id=current_department_id,
                    )
                )

        self.fields["program"].queryset = (
            program_queryset.select_related(
                "department"
            ).order_by("code")
        )

        self.fields["program"].empty_label = (
            "Select Program"
        )

        self.fields["department"].widget.attrs.update({
            "id": "id_department",
        })

        self.fields["program"].widget.attrs.update({
            "id": "id_program",
        })

    def clean(self):
        cleaned_data = super().clean()

        department = cleaned_data.get("department")
        program = cleaned_data.get("program")

        if department and program:
            if program.department_id != department.pk:
                self.add_error(
                    "program",
                    "Selected program does not belong "
                    "to the selected department.",
                )

        return cleaned_data


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
