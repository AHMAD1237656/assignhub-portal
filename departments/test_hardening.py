
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import UserProfile
from .models import Department, Program


User = get_user_model()


class DepartmentHardeningTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="hardening_admin",
            email="hardening@example.com",
            password="StrongTestPassword123!",
        )

        cls.teacher = User.objects.create_user(
            username="hardening_teacher",
            password="StrongTestPassword123!",
            is_staff=True,
        )

        UserProfile.objects.create(
            user=cls.teacher,
            role=UserProfile.Role.TEACHER,
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

    def setUp(self):
        self.client.force_login(self.admin)

    def department_toggle_url(self):
        return reverse(
            "departments:department_toggle",
            args=[self.department.pk],
        )

    def program_toggle_url(self):
        return reverse(
            "departments:program_toggle",
            args=[self.program.pk],
        )

    # =================================================
    # DATABASE VALIDATION
    # =================================================

    def test_program_duration_one_allowed(self):
        program = Program.objects.create(
            department=self.department,
            code="SHORT",
            name="Short Program",
            duration_semesters=1,
        )

        self.assertEqual(
            program.duration_semesters,
            1,
        )

    def test_program_duration_twelve_allowed(self):
        program = Program.objects.create(
            department=self.department,
            code="LONG",
            name="Long Program",
            duration_semesters=12,
        )

        self.assertEqual(
            program.duration_semesters,
            12,
        )

    def test_database_rejects_zero_semesters(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Program.objects.create(
                    department=self.department,
                    code="INVALID0",
                    name="Invalid Zero",
                    duration_semesters=0,
                )

    def test_database_rejects_thirteen_semesters(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Program.objects.create(
                    department=self.department,
                    code="INVALID13",
                    name="Invalid Thirteen",
                    duration_semesters=13,
                )

    # =================================================
    # EXPLICIT PROGRAM ARCHIVE / RESTORE
    # =================================================

    def test_explicit_program_archive(self):
        response = self.client.post(
            self.program_toggle_url(),
            {"action": "archive"},
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.program.refresh_from_db()

        self.assertFalse(
            self.program.is_active
        )

    def test_program_archive_is_idempotent(self):
        for _ in range(2):
            response = self.client.post(
                self.program_toggle_url(),
                {"action": "archive"},
            )

            self.assertEqual(
                response.status_code,
                302,
            )

        self.program.refresh_from_db()

        self.assertFalse(
            self.program.is_active
        )

    def test_program_restore_is_idempotent(self):
        self.program.is_active = False
        self.program.save()

        for _ in range(2):
            response = self.client.post(
                self.program_toggle_url(),
                {"action": "restore"},
            )

            self.assertEqual(
                response.status_code,
                302,
            )

        self.program.refresh_from_db()

        self.assertTrue(
            self.program.is_active
        )

    def test_invalid_program_action_rejected(self):
        original_status = self.program.is_active

        response = self.client.post(
            self.program_toggle_url(),
            {"action": "invalid-action"},
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.program.refresh_from_db()

        self.assertEqual(
            self.program.is_active,
            original_status,
        )

    # =================================================
    # EXPLICIT DEPARTMENT ARCHIVE / RESTORE
    # =================================================

    def test_department_archive_blocked_if_program_active(self):
        response = self.client.post(
            self.department_toggle_url(),
            {"action": "archive"},
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.department.refresh_from_db()

        self.assertTrue(
            self.department.is_active
        )

    def test_department_archive_is_idempotent(self):
        self.client.post(
            self.program_toggle_url(),
            {"action": "archive"},
        )

        for _ in range(2):
            response = self.client.post(
                self.department_toggle_url(),
                {"action": "archive"},
            )

            self.assertEqual(
                response.status_code,
                302,
            )

        self.department.refresh_from_db()

        self.assertFalse(
            self.department.is_active
        )

    def test_department_restore_is_idempotent(self):
        self.client.post(
            self.program_toggle_url(),
            {"action": "archive"},
        )

        self.client.post(
            self.department_toggle_url(),
            {"action": "archive"},
        )

        for _ in range(2):
            self.client.post(
                self.department_toggle_url(),
                {"action": "restore"},
            )

        self.department.refresh_from_db()

        self.assertTrue(
            self.department.is_active
        )

    def test_program_cannot_restore_under_archived_department(self):
        self.client.post(
            self.program_toggle_url(),
            {"action": "archive"},
        )

        self.client.post(
            self.department_toggle_url(),
            {"action": "archive"},
        )

        response = self.client.post(
            self.program_toggle_url(),
            {"action": "restore"},
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.program.refresh_from_db()

        self.assertFalse(
            self.program.is_active
        )

    def test_invalid_department_action_rejected(self):
        response = self.client.post(
            self.department_toggle_url(),
            {"action": "invalid"},
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.department.refresh_from_db()

        self.assertTrue(
            self.department.is_active
        )

    # =================================================
    # LEGACY COMPATIBILITY
    # =================================================

    def test_legacy_program_toggle_still_works(self):
        self.client.post(
            self.program_toggle_url()
        )

        self.program.refresh_from_db()

        self.assertFalse(
            self.program.is_active
        )

    # =================================================
    # DEPARTMENT EDIT VALIDATION
    # =================================================

    def test_edit_cannot_archive_with_active_program(self):
        url = reverse(
            "departments:department_edit",
            args=[self.department.pk],
        )

        # Omitted checkbox means is_active=False.
        response = self.client.post(
            url,
            {
                "code": "CS",
                "name": "Computer Science",
                "description": "Test",
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.department.refresh_from_db()

        self.assertTrue(
            self.department.is_active
        )

    # =================================================
    # HTTP METHOD SECURITY
    # =================================================

    def test_department_list_rejects_post(self):
        response = self.client.post(
            reverse(
                "departments:department_list"
            )
        )

        self.assertEqual(
            response.status_code,
            405,
        )

    def test_program_list_rejects_post(self):
        response = self.client.post(
            reverse(
                "departments:program_list"
            )
        )

        self.assertEqual(
            response.status_code,
            405,
        )

    def test_department_create_rejects_put(self):
        response = self.client.put(
            reverse(
                "departments:department_create"
            ),
            data="unexpected-data",
            content_type="text/plain",
        )

        self.assertEqual(
            response.status_code,
            405,
        )

    def test_program_create_rejects_put(self):
        response = self.client.put(
            reverse(
                "departments:program_create"
            ),
            data="unexpected-data",
            content_type="text/plain",
        )

        self.assertEqual(
            response.status_code,
            405,
        )

    def test_department_toggle_rejects_get(self):
        response = self.client.get(
            self.department_toggle_url()
        )

        self.assertEqual(
            response.status_code,
            405,
        )

    def test_program_toggle_rejects_get(self):
        response = self.client.get(
            self.program_toggle_url()
        )

        self.assertEqual(
            response.status_code,
            405,
        )

    # =================================================
    # REQUEST INPUT VALIDATION
    # =================================================

    def test_long_search_is_limited(self):
        response = self.client.get(
            reverse(
                "departments:department_list"
            ),
            {
                "q": "A" * 500,
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertLessEqual(
            len(response.context["search"]),
            100,
        )

    def test_large_department_filter_is_safe(self):
        response = self.client.get(
            reverse(
                "departments:program_list"
            ),
            {
                "department": "9" * 500,
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            len(response.context["page_obj"]),
            0,
        )

    def test_invalid_status_filter_defaults_to_all(self):
        response = self.client.get(
            reverse(
                "departments:department_list"
            ),
            {
                "status": "INVALID",
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.context["status"],
            "all",
        )

    # =================================================
    # AUTHORIZATION AND CSRF
    # =================================================

    def test_teacher_cannot_archive_department(self):
        self.client.force_login(self.teacher)

        response = self.client.post(
            self.department_toggle_url(),
            {"action": "archive"},
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.department.refresh_from_db()

        self.assertTrue(
            self.department.is_active
        )

    def test_teacher_cannot_archive_program(self):
        self.client.force_login(self.teacher)

        response = self.client.post(
            self.program_toggle_url(),
            {"action": "archive"},
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.program.refresh_from_db()

        self.assertTrue(
            self.program.is_active
        )

    def test_archive_requires_csrf_token(self):
        secure_client = Client(
            enforce_csrf_checks=True
        )

        secure_client.force_login(
            self.admin
        )

        response = secure_client.post(
            self.program_toggle_url(),
            {"action": "archive"},
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.program.refresh_from_db()

        self.assertTrue(
            self.program.is_active
        )
