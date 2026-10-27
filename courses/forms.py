
from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from accounts.models import UserProfile
from departments.models import Program
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

        current_program = (
            self.instance.program_id
            if self.instance.pk
            else None
        )

        programs = Program.objects.filter(
            is_active=True,
            department__is_active=True,
        )

        if current_program:
            programs = Program.objects.filter(
                Q(
                    is_active=True,
                    department__is_active=True,
                )
                | Q(pk=current_program)
            )

        self.fields["program"].queryset = (
            programs.order_by("code", "pk")
        )

        selected_program = (
            safe_selected_id(
                self.data.get(self.add_prefix("program"))
            )
            if self.is_bound
            else current_program
        )

        if not selected_program:
            selected_program = safe_selected_id(
                self.initial.get("program")
            )

        semester_query = Semester.objects.none()

        if selected_program:
            semester_query = Semester.objects.filter(
                program_id=selected_program,
                is_active=True,
                program__is_active=True,
                program__department__is_active=True,
            )

        if self.instance.pk:
            semester_query = Semester.objects.filter(
                Q(pk__in=semester_query.values("pk"))
                | Q(pk=self.instance.semester_id)
            )

        self.fields["semester"].queryset = (
            semester_query.order_by("number", "pk")
        )

    def clean_code(self):
        return (
            self.cleaned_data["code"]
            .strip()
            .upper()
        )


class CourseOfferingForm(AcademicModelForm):

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

        active_courses = Course.objects.filter(
            is_active=True,
            program__is_active=True,
            program__department__is_active=True,
            semester__is_active=True,
        )

        if self.instance.pk:
            active_courses = Course.objects.filter(
                Q(pk__in=active_courses.values("pk"))
                | Q(pk=self.instance.course_id)
            )

        self.fields["course"].queryset = (
            active_courses.select_related(
                "program",
                "semester",
            ).order_by(
                "program__code",
                "semester__number",
                "code",
            )
        )

        selected_course = (
            safe_selected_id(
                self.data.get(self.add_prefix("course"))
            )
            if self.is_bound
            else (
                self.instance.course_id
                if self.instance.pk
                else None
            )
        )

        if not selected_course:
            selected_course = safe_selected_id(
                self.initial.get("course")
            )

        section_query = Section.objects.none()

        if selected_course:
            section_query = Section.objects.filter(
                semester__courses__pk=selected_course,
                is_active=True,
                semester__is_active=True,
                semester__program__is_active=True,
                semester__program__department__is_active=True,
            )

        if self.instance.pk:
            section_query = Section.objects.filter(
                Q(pk__in=section_query.values("pk"))
                | Q(pk=self.instance.section_id)
            )

        self.fields["section"].queryset = (
            section_query.distinct().order_by(
                "code",
                "pk",
            )
        )

        teacher_ids = UserProfile.objects.filter(
            role=UserProfile.Role.TEACHER
        ).values("user_id")

        teacher_query = User.objects.filter(
            pk__in=teacher_ids,
            is_active=True,
        )

        if self.instance.pk:
            teacher_query = User.objects.filter(
                Q(pk__in=teacher_query.values("pk"))
                | Q(pk=self.instance.teacher_id)
            )

        self.fields["teacher"].queryset = (
            teacher_query.order_by(
                "username",
                "pk",
            )
        )

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
