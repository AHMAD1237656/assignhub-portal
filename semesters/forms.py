
from django import forms
from django.db.models import Q

from departments.models import Department, Program
from .models import Section, Semester


class StyledModelForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                css_class = "form-check-input"
            elif isinstance(field.widget, forms.Select):
                css_class = "form-select"
            else:
                css_class = "form-control"

            field.widget.attrs["class"] = css_class


class SemesterForm(StyledModelForm):

    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        required=False,
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
            if self.instance.pk else None
        )

        current_department_id = (
            self.instance.program.department_id
            if self.instance.pk else None
        )

        if self.is_bound:
            department_id = self.data.get(
                self.add_prefix("department")
            )
            program_id = self.data.get(
                self.add_prefix("program")
            )

            # Backward compatibility:
            # Infer department from submitted program if omitted.
            if not department_id and program_id:
                department_id = (
                    Program.objects.filter(pk=program_id)
                    .values_list("department_id", flat=True)
                    .first()
                )
        else:
            department_id = (
                self.initial.get("department")
                or current_department_id
            )

        departments = Department.objects.filter(is_active=True)

        if current_department_id:
            departments = (
                departments
                | Department.objects.filter(
                    pk=current_department_id
                )
            )

        self.fields["department"].queryset = (
            departments.order_by("name")
        )

        programs = Program.objects.none()

        if department_id:
            programs = Program.objects.filter(
                department_id=department_id,
                is_active=True,
                department__is_active=True,
            )

            if (
                current_program_id
                and str(department_id) == str(current_department_id)
            ):
                programs = (
                    programs
                    | Program.objects.filter(
                        pk=current_program_id,
                        department_id=current_department_id,
                    )
                )

        self.fields["program"].queryset = (
            programs.select_related("department").order_by("code")
        )

        self.fields["program"].empty_label = "Select Program"

        self.fields["department"].widget.attrs["id"] = "id_department"
        self.fields["program"].widget.attrs["id"] = "id_program"

    def clean(self):
        cleaned_data = super().clean()

        department = cleaned_data.get("department")
        program = cleaned_data.get("program")

        # Infer department for legacy POST requests.
        if not department and program:
            department = program.department
            cleaned_data["department"] = department

        if department and program:
            if program.department_id != department.pk:
                self.add_error(
                    "program",
                    "Selected program does not belong "
                    "to the selected department.",
                )

        return cleaned_data


class SectionForm(StyledModelForm):

    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        required=False,
        label="Department",
        empty_label="Select Department",
    )

    program = forms.ModelChoiceField(
        queryset=Program.objects.none(),
        required=False,
        label="Program",
        empty_label="Select Program",
    )

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

        current_semester = (
            self.instance.semester
            if self.instance.pk else None
        )

        current_program_id = (
            current_semester.program_id
            if current_semester else None
        )

        current_department_id = (
            current_semester.program.department_id
            if current_semester else None
        )

        if self.is_bound:
            department_id = self.data.get(
                self.add_prefix("department")
            )
            program_id = self.data.get(
                self.add_prefix("program")
            )
            semester_id = self.data.get(
                self.add_prefix("semester")
            )

            # Infer missing hierarchy fields from submitted semester.
            submitted_semester = None

            if semester_id:
                submitted_semester = (
                    Semester.objects
                    .select_related("program", "program__department")
                    .filter(pk=semester_id)
                    .first()
                )

            if submitted_semester:
                if not department_id:
                    department_id = (
                        submitted_semester.program.department_id
                    )

                if not program_id:
                    program_id = submitted_semester.program_id

            # If only program is provided, infer its department.
            if not department_id and program_id:
                department_id = (
                    Program.objects.filter(pk=program_id)
                    .values_list("department_id", flat=True)
                    .first()
                )

        else:
            department_id = (
                self.initial.get("department")
                or current_department_id
            )

            program_id = (
                self.initial.get("program")
                or current_program_id
            )

        departments = Department.objects.filter(is_active=True)

        if current_department_id:
            departments = (
                departments
                | Department.objects.filter(
                    pk=current_department_id
                )
            )

        self.fields["department"].queryset = (
            departments.order_by("name")
        )

        programs = Program.objects.none()

        if department_id:
            programs = Program.objects.filter(
                department_id=department_id,
                is_active=True,
                department__is_active=True,
            )

            if (
                current_program_id
                and str(department_id) == str(current_department_id)
            ):
                programs = (
                    programs
                    | Program.objects.filter(
                        pk=current_program_id,
                        department_id=current_department_id,
                    )
                )

        self.fields["program"].queryset = (
            programs.select_related("department").order_by("code")
        )

        semesters = Semester.objects.none()

        if program_id:
            semesters = Semester.objects.filter(
                program_id=program_id,
                is_active=True,
                program__is_active=True,
                program__department__is_active=True,
            )

            if (
                current_semester
                and str(program_id) == str(current_program_id)
            ):
                semesters = (
                    semesters
                    | Semester.objects.filter(
                        pk=current_semester.pk
                    )
                )

        self.fields["semester"].queryset = (
            semesters
            .select_related("program", "program__department")
            .order_by("number")
        )

        self.order_fields([
            "department",
            "program",
            "semester",
            "code",
            "capacity",
            "description",
            "is_active",
        ])

        self.fields["department"].widget.attrs["id"] = "id_department"
        self.fields["program"].widget.attrs["id"] = "id_program"
        self.fields["semester"].widget.attrs["id"] = "id_semester"

    def clean(self):
        cleaned = super().clean()

        department = cleaned.get("department")
        program = cleaned.get("program")
        semester = cleaned.get("semester")

        # Backward compatibility for legacy POST requests.
        if semester:
            if not program:
                program = semester.program
                cleaned["program"] = program

            if not department:
                department = semester.program.department
                cleaned["department"] = department

        if department and program:
            if program.department_id != department.pk:
                self.add_error(
                    "program",
                    "Selected program does not belong to the selected department.",
                )

        if program and semester:
            if semester.program_id != program.pk:
                self.add_error(
                    "semester",
                    "Selected semester does not belong to the selected program.",
                )

        if department and semester:
            if semester.program.department_id != department.pk:
                self.add_error(
                    "semester",
                    "Selected semester does not belong to the selected department.",
                )

        return cleaned

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()
