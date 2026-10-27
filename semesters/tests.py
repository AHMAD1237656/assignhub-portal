
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import (
    Client,
    TestCase,
    override_settings,
)
from django.urls import reverse

from accounts.models import UserProfile
from departments.models import Department, Program

from .forms import SectionForm, SemesterForm
from .models import Section, Semester


User = get_user_model()


def semester_data(program_id, **changes):
    data = {
        "program": program_id,
        "number": 3,
        "description": "Test semester",
        "is_active": "on",
    }

    data.update(changes)
    return data


def section_data(semester_id, **changes):
    data = {
        "semester": semester_id,
        "code": "C",
        "capacity": 40,
        "description": "Test section",
        "is_active": "on",
    }

    data.update(changes)
    return data


@override_settings(
    PASSWORD_HASHERS=[
        "django.contrib.auth.hashers.MD5PasswordHasher",
    ]
)
class AcademicTestBase(TestCase):

    @classmethod
    def setUpTestData(cls):

        cls.admin = User.objects.create_superuser(
            username="semester_admin",
            email="semadmin@example.com",
            password="TestPassword123!",
        )

        cls.staff_admin = User.objects.create_user(
            username="semester_staff_admin",
            password="TestPassword123!",
            is_staff=True,
        )

        UserProfile.objects.create(
            user=cls.staff_admin,
            role=UserProfile.Role.ADMIN,
        )

        cls.teacher = User.objects.create_user(
            username="semester_teacher",
            password="TestPassword123!",
            is_staff=True,
        )

        UserProfile.objects.create(
            user=cls.teacher,
            role=UserProfile.Role.TEACHER,
        )

        cls.student = User.objects.create_user(
            username="semester_student",
            password="TestPassword123!",
        )

        UserProfile.objects.create(
            user=cls.student,
            role=UserProfile.Role.STUDENT,
        )

        cls.department = Department.objects.create(
            code="CS",
            name="Computer Science",
        )

        cls.program = Program.objects.create(
            department=cls.department,
            code="BSCS",
            name="BS Computer Science",
            duration_semesters=8,
        )

        cls.other_program = Program.objects.create(
            department=cls.department,
            code="BSSE",
            name="BS Software Engineering",
            duration_semesters=8,
        )

        cls.semester1 = Semester.objects.create(
            program=cls.program,
            number=1,
        )

        cls.semester2 = Semester.objects.create(
            program=cls.program,
            number=2,
        )

        cls.other_semester = Semester.objects.create(
            program=cls.other_program,
            number=1,
        )

        cls.section_a = Section.objects.create(
            semester=cls.semester1,
            code="A",
            capacity=40,
        )

        cls.section_b = Section.objects.create(
            semester=cls.semester1,
            code="B",
            capacity=50,
        )

        cls.section_other = Section.objects.create(
            semester=cls.semester2,
            code="A",
            capacity=35,
        )

        cls.other_program_section = Section.objects.create(
            semester=cls.other_semester,
            code="A",
            capacity=30,
        )

    def login(self, user=None):
        self.client.force_login(
            user or self.admin
        )

    def url(self, name, pk=None):
        kwargs = {}

        if pk is not None:
            kwargs["pk"] = pk

        return reverse(
            f"semesters:{name}",
            kwargs=kwargs,
        )


# =====================================================
# PERMISSIONS
# =====================================================

class PermissionTests(AcademicTestBase):

    def test_anonymous_redirected(self):
        response = self.client.get(
            self.url("semester_list")
        )

        self.assertEqual(
            response.status_code,
            302,
        )

    def test_teacher_denied_semester_list(self):
        self.login(self.teacher)

        response = self.client.get(
            self.url("semester_list")
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_student_denied_sections(self):
        self.login(self.student)

        response = self.client.get(
            self.url("section_list")
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_teacher_cannot_create(self):
        self.login(self.teacher)

        response = self.client.post(
            self.url("semester_create"),
            semester_data(self.program.pk),
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertFalse(
            Semester.objects.filter(
                program=self.program,
                number=3,
            ).exists()
        )

    def test_student_cannot_delete(self):
        self.login(self.student)

        response = self.client.post(
            self.url(
                "section_delete",
                self.section_a.pk,
            )
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertTrue(
            Section.objects.filter(
                pk=self.section_a.pk
            ).exists()
        )

    def test_teacher_cannot_archive(self):
        self.login(self.teacher)

        response = self.client.post(
            self.url(
                "section_toggle",
                self.section_a.pk,
            ),
            {"action": "archive"},
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_teacher_cannot_use_json_api(self):
        self.login(self.teacher)

        response = self.client.get(
            self.url("semester_options_api"),
            {"program": self.program.pk},
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_staff_admin_allowed(self):
        self.login(self.staff_admin)

        response = self.client.get(
            self.url("semester_list")
        )

        self.assertEqual(
            response.status_code,
            200,
        )


# =====================================================
# SEMESTER CRUD
# =====================================================

class SemesterCRUDTests(AcademicTestBase):

    def setUp(self):
        self.login()

    def test_list_loads(self):
        response = self.client.get(
            self.url("semester_list")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_detail_loads(self):
        response = self.client.get(
            self.url(
                "semester_detail",
                self.semester1.pk,
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_create(self):
        response = self.client.post(
            self.url("semester_create"),
            semester_data(self.program.pk),
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertTrue(
            Semester.objects.filter(
                program=self.program,
                number=3,
            ).exists()
        )

    def test_duplicate_semester_rejected(self):
        response = self.client.post(
            self.url("semester_create"),
            semester_data(
                self.program.pk,
                number=1,
            ),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            Semester.objects.filter(
                program=self.program,
                number=1,
            ).count(),
            1,
        )

    def test_same_semester_number_other_program(self):
        response = self.client.post(
            self.url("semester_create"),
            semester_data(
                self.other_program.pk,
                number=2,
            ),
        )

        self.assertEqual(
            response.status_code,
            302,
        )

    def test_semester_zero_rejected(self):
        response = self.client.post(
            self.url("semester_create"),
            semester_data(
                self.program.pk,
                number=0,
            ),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            "number",
            response.context["form"].errors,
        )

    def test_semester_above_program_duration_rejected(self):
        self.program.duration_semesters = 4
        self.program.save()

        response = self.client.post(
            self.url("semester_create"),
            semester_data(
                self.program.pk,
                number=5,
            ),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            "number",
            response.context["form"].errors,
        )

    def test_edit_semester(self):
        response = self.client.post(
            self.url(
                "semester_edit",
                self.semester2.pk,
            ),
            semester_data(
                self.program.pk,
                number=2,
                description="Updated",
            ),
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.semester2.refresh_from_db()

        self.assertEqual(
            self.semester2.description,
            "Updated",
        )

    def test_archive_blocked_with_active_sections(self):
        self.client.post(
            self.url(
                "semester_toggle",
                self.semester1.pk,
            ),
            {"action": "archive"},
        )

        self.semester1.refresh_from_db()

        self.assertTrue(
            self.semester1.is_active
        )

    def test_archive_after_sections_archived(self):
        self.section_a.is_active = False
        self.section_a.save()

        self.section_b.is_active = False
        self.section_b.save()

        response = self.client.post(
            self.url(
                "semester_toggle",
                self.semester1.pk,
            ),
            {"action": "archive"},
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.semester1.refresh_from_db()

        self.assertFalse(
            self.semester1.is_active
        )

    def test_double_archive_safe(self):
        self.section_a.is_active = False
        self.section_a.save()

        self.section_b.is_active = False
        self.section_b.save()

        for _ in range(2):
            self.client.post(
                self.url(
                    "semester_toggle",
                    self.semester1.pk,
                ),
                {"action": "archive"},
            )

        self.semester1.refresh_from_db()

        self.assertFalse(
            self.semester1.is_active
        )

    def test_delete_semester_with_sections_blocked(self):
        response = self.client.post(
            self.url(
                "semester_delete",
                self.semester1.pk,
            )
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertTrue(
            Semester.objects.filter(
                pk=self.semester1.pk
            ).exists()
        )

    def test_delete_empty_semester(self):
        empty = Semester.objects.create(
            program=self.program,
            number=5,
        )

        response = self.client.post(
            self.url(
                "semester_delete",
                empty.pk,
            )
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertFalse(
            Semester.objects.filter(
                pk=empty.pk
            ).exists()
        )

    def test_get_toggle_not_allowed(self):
        response = self.client.get(
            self.url(
                "semester_toggle",
                self.semester1.pk,
            )
        )

        self.assertEqual(
            response.status_code,
            405,
        )

    def test_missing_record_returns_404(self):
        response = self.client.get(
            self.url(
                "semester_detail",
                999999,
            )
        )

        self.assertEqual(
            response.status_code,
            404,
        )


# =====================================================
# SECTION CRUD
# =====================================================

class SectionCRUDTests(AcademicTestBase):

    def setUp(self):
        self.login()

    def test_list_loads(self):
        response = self.client.get(
            self.url("section_list")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_detail_loads(self):
        response = self.client.get(
            self.url(
                "section_detail",
                self.section_a.pk,
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_create(self):
        response = self.client.post(
            self.url("section_create"),
            section_data(
                self.semester1.pk,
                code="C",
            ),
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertTrue(
            Section.objects.filter(
                semester=self.semester1,
                code="C",
            ).exists()
        )

    def test_code_normalized_to_uppercase(self):
        response = self.client.post(
            self.url("section_create"),
            section_data(
                self.semester1.pk,
                code="c",
            ),
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertTrue(
            Section.objects.filter(
                semester=self.semester1,
                code="C",
            ).exists()
        )

    def test_duplicate_code_rejected(self):
        response = self.client.post(
            self.url("section_create"),
            section_data(
                self.semester1.pk,
                code="a",
            ),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            Section.objects.filter(
                semester=self.semester1,
                code="A",
            ).count(),
            1,
        )

    def test_same_code_other_semester_allowed(self):
        response = self.client.post(
            self.url("section_create"),
            section_data(
                self.semester2.pk,
                code="B",
            ),
        )

        self.assertEqual(
            response.status_code,
            302,
        )

    def test_invalid_capacity_rejected(self):
        response = self.client.post(
            self.url("section_create"),
            section_data(
                self.semester1.pk,
                capacity=0,
            ),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            "capacity",
            response.context["form"].errors,
        )

    def test_capacity_above_500_rejected(self):
        response = self.client.post(
            self.url("section_create"),
            section_data(
                self.semester1.pk,
                capacity=501,
            ),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_edit(self):
        response = self.client.post(
            self.url(
                "section_edit",
                self.section_a.pk,
            ),
            section_data(
                self.semester1.pk,
                code="A",
                capacity=60,
            ),
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.section_a.refresh_from_db()

        self.assertEqual(
            self.section_a.capacity,
            60,
        )

    def test_archive(self):
        response = self.client.post(
            self.url(
                "section_toggle",
                self.section_a.pk,
            ),
            {"action": "archive"},
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.section_a.refresh_from_db()

        self.assertFalse(
            self.section_a.is_active
        )

    def test_restore(self):
        self.section_a.is_active = False
        self.section_a.save()

        response = self.client.post(
            self.url(
                "section_toggle",
                self.section_a.pk,
            ),
            {"action": "restore"},
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.section_a.refresh_from_db()

        self.assertTrue(
            self.section_a.is_active
        )

    def test_restore_under_inactive_semester_blocked(self):
        self.section_a.is_active = False
        self.section_a.save()

        self.section_b.is_active = False
        self.section_b.save()

        self.semester1.is_active = False
        self.semester1.save()

        response = self.client.post(
            self.url(
                "section_toggle",
                self.section_a.pk,
            ),
            {"action": "restore"},
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.section_a.refresh_from_db()

        self.assertFalse(
            self.section_a.is_active
        )

    def test_delete(self):
        pk = self.section_a.pk

        response = self.client.post(
            self.url(
                "section_delete",
                pk,
            )
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertFalse(
            Section.objects.filter(
                pk=pk
            ).exists()
        )

    def test_delete_get_does_not_delete(self):
        response = self.client.get(
            self.url(
                "section_delete",
                self.section_a.pk,
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertTrue(
            Section.objects.filter(
                pk=self.section_a.pk
            ).exists()
        )


# =====================================================
# LIVE SEARCH AND AJAX RESPONSES
# =====================================================

class LiveSearchTests(AcademicTestBase):

    def setUp(self):
        self.login()

    def test_semester_search_by_program(self):
        response = self.client.get(
            self.url("semester_list"),
            {"q": "BSCS"},
        )

        records = list(
            response.context["page_obj"]
        )

        self.assertEqual(
            len(records),
            2,
        )

        self.assertTrue(
            all(
                item.program_id == self.program.pk
                for item in records
            )
        )

    def test_semester_search_by_number(self):
        response = self.client.get(
            self.url("semester_list"),
            {"q": "2"},
        )

        records = list(
            response.context["page_obj"]
        )

        self.assertIn(
            self.semester2,
            records,
        )

    def test_semester_program_filter(self):
        response = self.client.get(
            self.url("semester_list"),
            {"program": self.program.pk},
        )

        records = list(
            response.context["page_obj"]
        )

        self.assertEqual(
            len(records),
            2,
        )

    def test_section_filter_by_semester(self):
        response = self.client.get(
            self.url("section_list"),
            {
                "program": self.program.pk,
                "semester": self.semester1.pk,
            },
        )

        records = list(
            response.context["page_obj"]
        )

        self.assertEqual(
            set(records),
            {
                self.section_a,
                self.section_b,
            },
        )

    def test_other_semester_sections_excluded(self):
        response = self.client.get(
            self.url("section_list"),
            {
                "program": self.program.pk,
                "semester": self.semester2.pk,
            },
        )

        records = list(
            response.context["page_obj"]
        )

        self.assertEqual(
            records,
            [self.section_other],
        )

    def test_cross_program_filter_returns_empty(self):
        response = self.client.get(
            self.url("section_list"),
            {
                "program": self.other_program.pk,
                "semester": self.semester1.pk,
            },
        )

        self.assertEqual(
            len(response.context["page_obj"]),
            0,
        )

    def test_search_matches_section_code(self):
        response = self.client.get(
            self.url("section_list"),
            {
                "q": "B",
                "program": self.program.pk,
            },
        )

        records = list(
            response.context["page_obj"]
        )

        self.assertIn(
            self.section_b,
            records,
        )

    def test_ajax_semester_returns_partial(self):
        response = self.client.get(
            self.url("semester_list"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertTemplateUsed(
            response,
            "semesters/partials/semester_results.html",
        )

        self.assertNotContains(
            response,
            "<!DOCTYPE html>",
        )

    def test_ajax_section_returns_partial(self):
        response = self.client.get(
            self.url("section_list"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertTemplateUsed(
            response,
            "semesters/partials/section_results.html",
        )

    def test_regular_page_uses_full_template(self):
        response = self.client.get(
            self.url("section_list")
        )

        self.assertTemplateUsed(
            response,
            "semesters/section_list.html",
        )

    def test_invalid_program_filter_safe(self):
        response = self.client.get(
            self.url("semester_list"),
            {"program": "bad-value"},
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            len(response.context["page_obj"]),
            0,
        )

    def test_invalid_page_safe(self):
        response = self.client.get(
            self.url("semester_list"),
            {"page": "abc"},
        )

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_long_numeric_filter_safe(self):
        response = self.client.get(
            self.url("section_list"),
            {
                "program": "9" * 500,
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_semester_pagination(self):
        for number in range(3, 9):
            Semester.objects.create(
                program=self.program,
                number=number,
            )

        for number in range(2, 9):
            Semester.objects.create(
                program=self.other_program,
                number=number,
            )

        response = self.client.get(
            self.url("semester_list")
        )

        self.assertEqual(
            len(response.context["page_obj"]),
            10,
        )

        self.assertGreater(
            response.context[
                "page_obj"
            ].paginator.num_pages,
            1,
        )


# =====================================================
# DEPENDENT DROPDOWN JSON APIs
# =====================================================

class DependentDropdownTests(AcademicTestBase):

    def setUp(self):
        self.login()

    def test_semesters_api_returns_correct_program(self):
        response = self.client.get(
            self.url("semester_options_api"),
            {
                "program": self.program.pk,
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        ids = [
            item["id"]
            for item in response.json()["results"]
        ]

        self.assertEqual(
            set(ids),
            {
                self.semester1.pk,
                self.semester2.pk,
            },
        )

    def test_sections_api_only_selected_semester(self):
        response = self.client.get(
            self.url("section_options_api"),
            {
                "semester": self.semester1.pk,
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        ids = [
            item["id"]
            for item in response.json()["results"]
        ]

        self.assertEqual(
            set(ids),
            {
                self.section_a.pk,
                self.section_b.pk,
            },
        )

    def test_sections_api_excludes_other_semester(self):
        response = self.client.get(
            self.url("section_options_api"),
            {
                "semester": self.semester1.pk,
            },
        )

        ids = [
            item["id"]
            for item in response.json()["results"]
        ]

        self.assertNotIn(
            self.section_other.pk,
            ids,
        )

    def test_archived_section_excluded(self):
        self.section_a.is_active = False
        self.section_a.save()

        response = self.client.get(
            self.url("section_options_api"),
            {
                "semester": self.semester1.pk,
            },
        )

        ids = [
            item["id"]
            for item in response.json()["results"]
        ]

        self.assertNotIn(
            self.section_a.pk,
            ids,
        )

    def test_invalid_program_api_returns_400(self):
        response = self.client.get(
            self.url("semester_options_api"),
            {"program": "invalid"},
        )

        self.assertEqual(
            response.status_code,
            400,
        )

    def test_missing_semester_api_returns_400(self):
        response = self.client.get(
            self.url("section_options_api")
        )

        self.assertEqual(
            response.status_code,
            400,
        )

    def test_nonexistent_semester_returns_empty(self):
        response = self.client.get(
            self.url("section_options_api"),
            {"semester": 999999},
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.json()["results"],
            [],
        )


# =====================================================
# MODEL INTEGRITY
# =====================================================

class AcademicModelTests(AcademicTestBase):

    def test_semester_string(self):
        self.assertEqual(
            str(self.semester1),
            "BSCS - Semester 1",
        )

    def test_section_string(self):
        self.assertIn(
            "Section A",
            str(self.section_a),
        )

    def test_program_semesters_relation(self):
        self.assertIn(
            self.semester1,
            self.program.semesters.all(),
        )

    def test_semester_sections_relation(self):
        self.assertIn(
            self.section_a,
            self.semester1.sections.all(),
        )

    def test_semester_database_uniqueness(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Semester.objects.create(
                    program=self.program,
                    number=1,
                )

    def test_section_case_insensitive_uniqueness(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Section.objects.create(
                    semester=self.semester1,
                    code="a",
                )

    def test_database_rejects_semester_zero(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Semester.objects.create(
                    program=self.program,
                    number=0,
                )

    def test_database_rejects_capacity_zero(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Section.objects.create(
                    semester=self.semester1,
                    code="Z",
                    capacity=0,
                )

    def test_full_clean_checks_parent_program(self):
        semester = Semester(
            program=self.program,
            number=10,
        )

        with self.assertRaises(ValidationError):
            semester.full_clean()

    def test_full_clean_rejects_inactive_parent(self):
        self.program.is_active = False
        self.program.save()

        semester = Semester(
            program=self.program,
            number=3,
        )

        with self.assertRaises(ValidationError):
            semester.full_clean()


# =====================================================
# REQUEST SECURITY
# =====================================================

class SecurityTests(AcademicTestBase):

    def setUp(self):
        self.login()

    def test_semester_create_requires_csrf(self):
        client = Client(
            enforce_csrf_checks=True
        )

        client.force_login(self.admin)

        response = client.post(
            self.url("semester_create"),
            semester_data(self.program.pk),
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_section_create_requires_csrf(self):
        client = Client(
            enforce_csrf_checks=True
        )

        client.force_login(self.admin)

        response = client.post(
            self.url("section_create"),
            section_data(self.semester1.pk),
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_status_requires_post(self):
        response = self.client.get(
            self.url(
                "section_toggle",
                self.section_a.pk,
            )
        )

        self.assertEqual(
            response.status_code,
            405,
        )

    def test_invalid_status_action_does_not_modify(self):
        response = self.client.post(
            self.url(
                "section_toggle",
                self.section_a.pk,
            ),
            {"action": "invalid"},
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.section_a.refresh_from_db()

        self.assertTrue(
            self.section_a.is_active
        )

    def test_ajax_still_checks_permissions(self):
        self.login(self.teacher)

        response = self.client.get(
            self.url("section_list"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_list_rejects_post(self):
        response = self.client.post(
            self.url("semester_list")
        )

        self.assertEqual(
            response.status_code,
            405,
        )


# =====================================================
# END-TO-END ADMIN WORKFLOW
# =====================================================

class EndToEndTests(AcademicTestBase):

    def test_create_archive_restore_delete_workflow(self):
        self.login()

        # Step 1: Create Semester 3.
        response = self.client.post(
            self.url("semester_create"),
            semester_data(
                self.program.pk,
                number=3,
            ),
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        semester = Semester.objects.get(
            program=self.program,
            number=3,
        )

        # Step 2: Create Section C.
        response = self.client.post(
            self.url("section_create"),
            section_data(
                semester.pk,
                code="C",
            ),
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        section = Section.objects.get(
            semester=semester,
            code="C",
        )

        # Step 3: Check dependent API.
        response = self.client.get(
            self.url("section_options_api"),
            {"semester": semester.pk},
        )

        self.assertEqual(
            len(response.json()["results"]),
            1,
        )

        # Step 4: Archive Section.
        self.client.post(
            self.url(
                "section_toggle",
                section.pk,
            ),
            {"action": "archive"},
        )

        section.refresh_from_db()

        self.assertFalse(
            section.is_active
        )

        # Step 5: Archive Semester.
        self.client.post(
            self.url(
                "semester_toggle",
                semester.pk,
            ),
            {"action": "archive"},
        )

        semester.refresh_from_db()

        self.assertFalse(
            semester.is_active
        )

        # Step 6: Restore Semester.
        self.client.post(
            self.url(
                "semester_toggle",
                semester.pk,
            ),
            {"action": "restore"},
        )

        semester.refresh_from_db()

        self.assertTrue(
            semester.is_active
        )

        # Step 7: Restore Section.
        self.client.post(
            self.url(
                "section_toggle",
                section.pk,
            ),
            {"action": "restore"},
        )

        section.refresh_from_db()

        self.assertTrue(
            section.is_active
        )

        # Step 8: Delete Section.
        section_pk = section.pk

        self.client.post(
            self.url(
                "section_delete",
                section_pk,
            )
        )

        self.assertFalse(
            Section.objects.filter(
                pk=section_pk
            ).exists()
        )

        # Step 9: Delete Semester.
        semester_pk = semester.pk

        self.client.post(
            self.url(
                "semester_delete",
                semester_pk,
            )
        )

        self.assertFalse(
            Semester.objects.filter(
                pk=semester_pk
            ).exists()
        )
