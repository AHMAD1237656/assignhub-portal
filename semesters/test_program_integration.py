
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from departments.models import Department, Program
from semesters.models import Section, Semester


User = get_user_model()


class ProgramIntegrationTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="integration_admin",
            email="integration@example.com",
            password="TestPassword123!",
        )

        cls.department = Department.objects.create(
            code="IT",
            name="Information Technology",
        )

        cls.program = Program.objects.create(
            department=cls.department,
            code="BSIT",
            name="BS Information Technology",
            duration_semesters=8,
        )

        cls.semester = Semester.objects.create(
            program=cls.program,
            number=8,
        )

        cls.section = Section.objects.create(
            semester=cls.semester,
            code="A",
            capacity=40,
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def program_data(self, **changes):
        data = {
            "department": self.department.pk,
            "code": "BSIT",
            "name": "BS Information Technology",
            "duration_semesters": 8,
            "description": "",
            "is_active": "on",
        }
        data.update(changes)
        return data

    def test_duration_reduction_blocked(self):
        response = self.client.post(
            reverse(
                "departments:program_edit",
                args=[self.program.pk],
            ),
            self.program_data(
                duration_semesters=6,
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

        self.program.refresh_from_db()

        self.assertEqual(
            self.program.duration_semesters,
            8,
        )

    def test_program_archive_blocked_with_active_semester(self):
        response = self.client.post(
            reverse(
                "departments:program_toggle",
                args=[self.program.pk],
            ),
            {"action": "archive"},
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.program.refresh_from_db()

        self.assertTrue(
            self.program.is_active
        )

    def test_program_delete_blocked_by_semester(self):
        response = self.client.post(
            reverse(
                "departments:program_delete",
                args=[self.program.pk],
            )
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertTrue(
            Program.objects.filter(
                pk=self.program.pk
            ).exists()
        )

    def test_complete_archive_hierarchy(self):
        # Archive Section.
        self.client.post(
            reverse(
                "semesters:section_toggle",
                args=[self.section.pk],
            ),
            {"action": "archive"},
        )

        # Archive Semester.
        self.client.post(
            reverse(
                "semesters:semester_toggle",
                args=[self.semester.pk],
            ),
            {"action": "archive"},
        )

        # Archive Program.
        response = self.client.post(
            reverse(
                "departments:program_toggle",
                args=[self.program.pk],
            ),
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

        # Archive Department.
        response = self.client.post(
            reverse(
                "departments:department_toggle",
                args=[self.department.pk],
            ),
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
