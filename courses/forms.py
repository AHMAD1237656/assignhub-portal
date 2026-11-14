
from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from accounts.models import UserProfile
from departments.models import Department, Program
from semesters.models import Section, Semester

from .models import (
    Course,
    CourseEnrollment,
    CourseOffering,
)


User = get_user_model()


def safe_selected_id(value):
    value = str(value or "").strip()

    if (
        value.isascii()
        and value.isdecimal()
        and 0 < len(value) <= 18
    ):
        number = int(value)
        return number if number > 0 else None

    return None


class AcademicModelForm(forms.ModelForm):

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



class CourseForm(AcademicModelForm):

    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        required=False,
        label="Department",
        empty_label="Select Department",
    )

    class Meta:
        model = Course

        fields = [
            "program",
            "semester",
            "code",
            "title",
            "credit_hours",
            "description",
            "is_active",
        ]

        widgets = {
            "description": forms.Textarea(
                attrs={"rows": 3}
            ),
            "credit_hours": forms.NumberInput(
                attrs={"min": 1, "max": 6}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.order_fields([
            "department",
            "program",
            "semester",
            "code",
            "title",
            "credit_hours",
            "description",
            "is_active",
        ])

        current_program = (
            self.instance.program_id
            if self.instance.pk else None
        )

        current_department = (
            self.instance.program.department_id
            if self.instance.pk else None
        )

        if self.is_bound:
            department_id = safe_selected_id(
                self.data.get(self.add_prefix("department"))
            )
            program_id = safe_selected_id(
                self.data.get(self.add_prefix("program"))
            )

            # Backward compatibility for older POST requests.
            if not department_id and program_id:
                department_id = (
                    Program.objects.filter(pk=program_id)
                    .values_list("department_id", flat=True)
                    .first()
                )
        else:
            program_id = (
                safe_selected_id(self.initial.get("program"))
                or current_program
            )

            department_id = (
                safe_selected_id(self.initial.get("department"))
                or current_department
            )

            if not department_id and program_id:
                department_id = (
                    Program.objects.filter(pk=program_id)
                    .values_list("department_id", flat=True)
                    .first()
                )

        departments = Department.objects.filter(
            is_active=True
        )

        if current_department:
            departments = (
                departments
                | Department.objects.filter(pk=current_department)
            )

        self.fields["department"].queryset = departments.order_by("name")

        programs = Program.objects.none()

        if department_id:
            programs = Program.objects.filter(
                department_id=department_id,
                is_active=True,
                department__is_active=True,
            )

            if current_program and current_department == department_id:
                programs = (
                    programs
                    | Program.objects.filter(pk=current_program)
                )

        self.fields["program"].queryset = programs.order_by("code", "pk")

        semesters = Semester.objects.none()

        if program_id:
            semesters = Semester.objects.filter(
                program_id=program_id,
                is_active=True,
                program__is_active=True,
                program__department__is_active=True,
            )

        if self.instance.pk:
            semesters = Semester.objects.filter(
                Q(pk__in=semesters.values("pk"))
                | Q(pk=self.instance.semester_id)
            )

        self.fields["semester"].queryset = semesters.order_by(
            "number", "pk"
        )

        self.fields["department"].widget.attrs["id"] = "id_department"
        self.fields["program"].widget.attrs["id"] = "id_program"
        self.fields["semester"].widget.attrs["id"] = "id_semester"

    def clean(self):
        cleaned_data = super().clean()

        department = cleaned_data.get("department")
        program = cleaned_data.get("program")
        semester = cleaned_data.get("semester")

        if program and not department:
            department = program.department
            cleaned_data["department"] = department

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

        return cleaned_data

    def clean_code(self):
        return (
            self.cleaned_data["code"]
            .strip()
            .upper()
        )



class CourseOfferingForm(AcademicModelForm):

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
        model = CourseOffering

        fields = [
            "course",
            "section",
            "teacher",
            "academic_year",
            "term",
            "is_active",
        ]

        widgets = {
            "academic_year": forms.TextInput(
                attrs={"placeholder": "2026-2027"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.order_fields([
            "department",
            "program",
            "course",
            "section",
            "teacher",
            "academic_year",
            "term",
            "is_active",
        ])

        current_course_id = (
            self.instance.course_id
            if self.instance.pk else None
        )

        current_program_id = None
        current_department_id = None

        if current_course_id:
            current_course_data = (
                Course.objects.filter(pk=current_course_id)
                .values(
                    "program_id",
                    "program__department_id",
                )
                .first()
            )

            if current_course_data:
                current_program_id = (
                    current_course_data["program_id"]
                )
                current_department_id = (
                    current_course_data["program__department_id"]
                )

        if self.is_bound:
            department_id = safe_selected_id(
                self.data.get(
                    self.add_prefix("department")
                )
            )

            program_id = safe_selected_id(
                self.data.get(
                    self.add_prefix("program")
                )
            )

            course_id = safe_selected_id(
                self.data.get(
                    self.add_prefix("course")
                )
            )

            # Backward compatibility with older POST requests.
            course_data = None

            if course_id:
                course_data = (
                    Course.objects.filter(pk=course_id)
                    .values(
                        "program_id",
                        "program__department_id",
                    )
                    .first()
                )

            if course_data:
                if not program_id:
                    program_id = course_data["program_id"]

                if not department_id:
                    department_id = (
                        course_data["program__department_id"]
                    )

            if not department_id and program_id:
                department_id = (
                    Program.objects.filter(pk=program_id)
                    .values_list(
                        "department_id",
                        flat=True,
                    )
                    .first()
                )

        else:
            department_id = (
                safe_selected_id(
                    self.initial.get("department")
                )
                or current_department_id
            )

            program_id = (
                safe_selected_id(
                    self.initial.get("program")
                )
                or current_program_id
            )

            course_id = (
                safe_selected_id(
                    self.initial.get("course")
                )
                or current_course_id
            )

        # Department queryset.
        departments = Department.objects.filter(
            is_active=True
        )

        if current_department_id:
            departments = (
                departments
                | Department.objects.filter(
                    pk=current_department_id
                )
            )

        self.fields["department"].queryset = (
            departments.order_by("name", "pk")
        )

        # Program queryset.
        programs = Program.objects.none()

        if department_id:
            programs = Program.objects.filter(
                department_id=department_id,
                is_active=True,
                department__is_active=True,
            )

        if current_program_id:
            programs = (
                programs
                | Program.objects.filter(
                    pk=current_program_id
                )
            )

        self.fields["program"].queryset = (
            programs.order_by("code", "pk")
        )

        # Course queryset.
        courses = Course.objects.none()

        if program_id:
            courses = Course.objects.filter(
                program_id=program_id,
                is_active=True,
                program__is_active=True,
                program__department__is_active=True,
                semester__is_active=True,
            )

        if current_course_id:
            courses = (
                courses
                | Course.objects.filter(
                    pk=current_course_id
                )
            )

        self.fields["course"].queryset = (
            courses.select_related(
                "program",
                "program__department",
                "semester",
            ).order_by(
                "program__code",
                "semester__number",
                "code",
                "pk",
            )
        )

        # Section queryset.
        section_query = Section.objects.none()

        if course_id:
            section_query = Section.objects.filter(
                semester__courses__pk=course_id,
                is_active=True,
                semester__is_active=True,
                semester__program__is_active=True,
                semester__program__department__is_active=True,
            )

        if self.instance.pk:
            section_query = (
                section_query
                | Section.objects.filter(
                    pk=self.instance.section_id
                )
            )

        self.fields["section"].queryset = (
            section_query.distinct().order_by(
                "code",
                "pk",
            )
        )

        # Teacher queryset.
        teacher_ids = UserProfile.objects.filter(
            role=UserProfile.Role.TEACHER
        ).values("user_id")

        teacher_query = User.objects.filter(
            pk__in=teacher_ids,
            is_active=True,
        )

        if self.instance.pk:
            teacher_query = (
                teacher_query
                | User.objects.filter(
                    pk=self.instance.teacher_id
                )
            )

        self.fields["teacher"].queryset = (
            teacher_query.order_by(
                "username",
                "pk",
            )
        )

        # Stable IDs for dependent JavaScript.
        self.fields["department"].widget.attrs["id"] = (
            "id_department"
        )

        self.fields["program"].widget.attrs["id"] = (
            "id_program"
        )

        self.fields["course"].widget.attrs["id"] = (
            "id_course"
        )

        self.fields["section"].widget.attrs["id"] = (
            "id_section"
        )

    def clean(self):
        cleaned_data = super().clean()

        department = cleaned_data.get("department")
        program = cleaned_data.get("program")
        course = cleaned_data.get("course")

        # Infer missing selection-only fields for legacy POSTs.
        if course:
            if not program:
                program = course.program
                cleaned_data["program"] = program

            if not department:
                department = course.program.department
                cleaned_data["department"] = department

        if program and department:
            if program.department_id != department.pk:
                self.add_error(
                    "program",
                    "Selected program does not belong "
                    "to the selected department.",
                )

        if course and program:
            if course.program_id != program.pk:
                self.add_error(
                    "course",
                    "Selected course does not belong "
                    "to the selected program.",
                )

        if course and department:
            if course.program.department_id != department.pk:
                self.add_error(
                    "course",
                    "Selected course does not belong "
                    "to the selected department.",
                )

        return cleaned_data

    def clean_academic_year(self):
        return (
            self.cleaned_data["academic_year"]
            .strip()
        )


class CourseEnrollmentForm(AcademicModelForm):

    class Meta:
        model = CourseEnrollment

        fields = [
            "offering",
            "student",
            "status",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        offerings = CourseOffering.objects.filter(
            is_active=True
        )

        if self.instance.pk:
            offerings = CourseOffering.objects.filter(
                Q(pk__in=offerings.values("pk"))
                | Q(pk=self.instance.offering_id)
            )

        self.fields["offering"].queryset = (
            offerings.select_related(
                "course",
                "section",
            ).order_by(
                "-academic_year",
                "course__code",
                "section__code",
            )
        )

        student_ids = UserProfile.objects.filter(
            role=UserProfile.Role.STUDENT
        ).values("user_id")

        students = User.objects.filter(
            is_active=True,
            pk__in=student_ids,
        )

        if self.instance.pk:
            students = User.objects.filter(
                Q(pk__in=students.values("pk"))
                | Q(pk=self.instance.student_id)
            )

        self.fields["student"].queryset = (
            students.order_by("username", "pk")
        )

        if self.instance.pk:
            # Existing enrollment identity stays fixed.
            self.fields["offering"].disabled = True
            self.fields["student"].disabled = True
