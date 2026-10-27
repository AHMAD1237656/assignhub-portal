
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import UserProfile
from assignments.permissions import is_admin
from departments.models import Department, Program
from semesters.models import Section, Semester


User = get_user_model()


@override_settings(
    PASSWORD_HASHERS=[
        "django.contrib.auth.hashers.MD5PasswordHasher",
    ]
)
class CrossModuleReadinessTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="readiness_admin",
            email="readiness@example.com",
            password="StrongTestPassword123!",
        )

        cls.staff_admin = User.objects.create_user(
            username="readiness_staff",
            password="StrongTestPassword123!",
            is_staff=True,
        )

        UserProfile.objects.create(
            user=cls.staff_admin,
            role=UserProfile.Role.ADMIN,
        )

        cls.nonstaff_admin = User.objects.create_user(
            username="readiness_nonstaff",
            password="StrongTestPassword123!",
            is_staff=False,
        )

        UserProfile.objects.create(
            user=cls.nonstaff_admin,
            role=UserProfile.Role.ADMIN,
        )

        cls.teacher = User.objects.create_user(
            username="readiness_teacher",
            password="StrongTestPassword123!",
        )

        UserProfile.objects.create(
            user=cls.teacher,
            role=UserProfile.Role.TEACHER,
        )

        cls.department = Department.objects.create(
            code="CS",
            name="Computer Science",
        )

        cls.other_department = Department.objects.create(
            code="IT",
            name="Information Technology",
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

        cls.section_a = Section.objects.create(
            semester=cls.semester1,
            code="A",
            capacity=40,
        )

        cls.section_b = Section.objects.create(
            semester=cls.semester2,
            code="B",
            capacity=45,
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def academic_url(self, name, pk=None):
        kwargs = {}

        if pk is not None:
            kwargs["pk"] = pk

        return reverse(
            f"semesters:{name}",
            kwargs=kwargs,
        )

    def semester_payload(self, **changes):
        data = {
            "program": self.program.pk,
            "number": 1,
            "description": "Test Semester",
            "is_active": "on",
        }

        data.update(changes)
        return data

    def section_payload(self, **changes):
        data = {
            "semester": self.semester1.pk,
            "code": "A",
            "capacity": 40,
            "description": "Test Section",
            "is_active": "on",
        }

        data.update(changes)
        return data

    def program_payload(self, **changes):
        data = {
            "department": self.department.pk,
            "code": "BSCS",
            "name": "BS Computer Science",
            "duration_semesters": 8,
            "description": "",
            "is_active": "on",
        }

        data.update(changes)
        return data

    # -----------------------------------------------
    # PERMISSION ALIGNMENT
    # -----------------------------------------------

    def test_superuser_is_assignments_admin(self):
        self.assertTrue(
            is_admin(self.admin)
        )

    def test_staff_admin_is_assignments_admin(self):
        self.assertTrue(
            is_admin(self.staff_admin)
        )

    def test_nonstaff_admin_profile_is_denied(self):
        self.assertFalse(
            is_admin(self.nonstaff_admin)
        )

    def test_teacher_is_not_assignments_admin(self):
        self.assertFalse(
            is_admin(self.teacher)
        )

    def test_nonstaff_admin_cannot_view_all_assignments(self):
        self.client.force_login(
            self.nonstaff_admin
        )

        response = self.client.get(
            reverse("assignments:list")
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_staff_admin_can_view_assignments(self):
        self.client.force_login(
            self.staff_admin
        )

        response = self.client.get(
            reverse("assignments:list")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

    # -----------------------------------------------
    # PROGRAM INTEGRITY
    # -----------------------------------------------

    def test_program_cannot_move_with_semesters(self):
        response = self.client.post(
            reverse(
                "departments:program_edit",
                args=[self.program.pk],
            ),
            self.program_payload(
                department=self.other_department.pk
            ),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            "department",
            response.context["form"].errors,
        )

        self.program.refresh_from_db()

        self.assertEqual(
            self.program.department_id,
            self.department.pk,
        )

    def test_program_description_remains_editable(self):
        response = self.client.post(
            reverse(
                "departments:program_edit",
                args=[self.program.pk],
            ),
            self.program_payload(
                description="Updated description"
            ),
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.program.refresh_from_db()

        self.assertEqual(
            self.program.description,
            "Updated description",
        )

    def test_program_duration_reduction_rejected(self):
        response = self.client.post(
            reverse(
                "departments:program_edit",
                args=[self.program.pk],
            ),
            self.program_payload(
                duration_semesters=0
            ),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            "duration_semesters",
            response.context["form"].errors,
        )

    # -----------------------------------------------
    # SEMESTER STRUCTURAL LOCKS
    # -----------------------------------------------

    def test_semester_cannot_change_program_with_sections(self):
        response = self.client.post(
            self.academic_url(
                "semester_edit",
                self.semester1.pk,
            ),
            self.semester_payload(
                program=self.other_program.pk
            ),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            "program",
            response.context["form"].errors,
        )

        self.semester1.refresh_from_db()

        self.assertEqual(
            self.semester1.program_id,
            self.program.pk,
        )

    def test_semester_number_locked_when_sections_exist(self):
        response = self.client.post(
            self.academic_url(
                "semester_edit",
                self.semester1.pk,
            ),
            self.semester_payload(number=3),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            "number",
            response.context["form"].errors,
        )

        self.semester1.refresh_from_db()

        self.assertEqual(
            self.semester1.number,
            1,
        )

    def test_semester_description_can_be_updated(self):
        response = self.client.post(
            self.academic_url(
                "semester_edit",
                self.semester1.pk,
            ),
            self.semester_payload(
                description="Updated description"
            ),
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.semester1.refresh_from_db()

        self.assertEqual(
            self.semester1.description,
            "Updated description",
        )

    # -----------------------------------------------
    # SECTION STRUCTURAL LOCK
    # -----------------------------------------------

    def test_section_cannot_move_to_another_semester(self):
        response = self.client.post(
            self.academic_url(
                "section_edit",
                self.section_a.pk,
            ),
            self.section_payload(
                semester=self.semester2.pk
            ),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            "semester",
            response.context["form"].errors,
        )

        self.section_a.refresh_from_db()

        self.assertEqual(
            self.section_a.semester_id,
            self.semester1.pk,
        )

    def test_section_capacity_remains_editable(self):
        response = self.client.post(
            self.academic_url(
                "section_edit",
                self.section_a.pk,
            ),
            self.section_payload(
                capacity=60
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

    # -----------------------------------------------
    # HIERARCHY VALIDATION
    # -----------------------------------------------

    def test_active_semester_rejects_inactive_department(self):
        # Simulate inconsistent external/bulk data.
        Department.objects.filter(
            pk=self.department.pk
        ).update(is_active=False)

        program = Program.objects.get(
            pk=self.program.pk
        )

        semester = Semester(
            program=program,
            number=3,
            is_active=True,
        )

        with self.assertRaises(ValidationError):
            semester.full_clean()

    def test_active_section_rejects_inactive_department(self):
        Department.objects.filter(
            pk=self.department.pk
        ).update(is_active=False)

        semester = Semester.objects.get(
            pk=self.semester1.pk
        )

        section = Section(
            semester=semester,
            code="C",
            capacity=40,
            is_active=True,
        )

        with self.assertRaises(ValidationError):
            section.full_clean()

    # -----------------------------------------------
    # SECTION FILTERING
    # -----------------------------------------------

    def test_selected_semester_only_shows_own_sections(self):
        response = self.client.get(
            self.academic_url("section_list"),
            {
                "program": self.program.pk,
                "semester": self.semester1.pk,
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        records = list(
            response.context["page_obj"]
        )

        self.assertEqual(
            records,
            [self.section_a],
        )

        self.assertNotIn(
            self.section_b,
            records,
        )

    def test_json_api_filters_by_semester(self):
        response = self.client.get(
            self.academic_url(
                "section_options_api"
            ),
            {
                "semester": self.semester1.pk,
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        ids = {
            item["id"]
            for item in response.json()["results"]
        }

        self.assertEqual(
            ids,
            {self.section_a.pk},
        )

    # -----------------------------------------------
    # AJAX & STATIC FILES
    # -----------------------------------------------

    def test_semester_ajax_renders_partial(self):
        response = self.client.get(
            self.academic_url(
                "semester_list"
            ),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertTemplateUsed(
            response,
            "semesters/partials/semester_results.html",
        )

    def test_section_ajax_renders_partial(self):
        response = self.client.get(
            self.academic_url(
                "section_list"
            ),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertTemplateUsed(
            response,
            "semesters/partials/section_results.html",
        )

    def test_live_search_script_is_discoverable(self):
        path = finders.find(
            "js/academic-live-search.js"
        )

        self.assertIsNotNone(
            path,
            "Live search JavaScript file "
            "was not found by Django staticfiles.",
        )

    def test_semester_search_has_200ms_setting(self):
        response = self.client.get(
            self.academic_url(
                "semester_list"
            )
        )

        self.assertContains(
            response,
            'data-debounce="200"',
        )

    def test_section_search_has_200ms_setting(self):
        response = self.client.get(
            self.academic_url(
                "section_list"
            )
        )

        self.assertContains(
            response,
            'data-debounce="200"',
        )
