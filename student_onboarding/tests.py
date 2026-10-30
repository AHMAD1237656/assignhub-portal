import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import UserProfile
from class_allocations.models import StudentClassAllocation
from courses.models import (
    Course,
    CourseEnrollment,
    CourseOffering,
)
from departments.models import Department, Program
from semesters.models import Semester, Section

from .models import (
    StudentIdentity,
    StudentImportBatch,
)
from .services import (
    make_activation_token,
    send_pending_activation_emails,
)


User = get_user_model()


@override_settings(
    MAILERS={
        "default": {
            "BACKEND": (
                "django.core.mail.backends.locmem.EmailBackend"
            ),
        }
    },
    ASSIGNHUB_PUBLIC_BASE_URL="https://testserver",
    STUDENT_EMAIL_DOMAIN="uni.edu",
)
class StudentOnboardingTests(TestCase):

    @classmethod
    def setUpTestData(cls):

        cls.admin = User.objects.create_superuser(
            username="onboarding_admin",
            email="admin@uni.edu",
            password="StrongAdminPass123!",
        )

        cls.teacher = User.objects.create_user(
            username="onboarding_teacher",
            email="teacher@uni.edu",
            password="StrongTeacherPass123!",
        )

        UserProfile.objects.create(
            user=cls.teacher,
            role=UserProfile.Role.TEACHER,
        )

        cls.student = User.objects.create_user(
            username="existing_student",
            email="existing@uni.edu",
            password="StrongStudentPass123!",
        )

        UserProfile.objects.create(
            user=cls.student,
            role=UserProfile.Role.STUDENT,
        )

        cls.department = Department.objects.create(
            code="ONB-DEP",
            name="Onboarding Test Department",
        )

        cls.program = Program.objects.create(
            department=cls.department,
            code="ONB-BSSE",
            name="Onboarding Software Engineering",
            duration_semesters=8,
        )

        cls.semester = Semester.objects.create(
            program=cls.program,
            number=1,
        )

        cls.section = Section.objects.create(
            semester=cls.semester,
            code="A",
            capacity=40,
        )

        cls.course = Course.objects.create(
            program=cls.program,
            semester=cls.semester,
            code="ONB101",
            title="Introduction to Computing",
            credit_hours=3,
        )

        cls.offering = CourseOffering.objects.create(
            course=cls.course,
            section=cls.section,
            teacher=cls.teacher,
            academic_year="2026-2027",
            term=CourseOffering.Term.FALL,
        )

    def csv_upload(self, body=None):
        if body is None:
            body = (
                "roll_number,first_name,last_name,email\n"
                "2026-SE-001,Ali,Ahmed,ali@uni.edu\n"
                "2026-SE-002,Hassan,Raza,hassan@uni.edu\n"
            )

        return SimpleUploadedFile(
            "students.csv",
            body.encode("utf-8"),
            content_type="text/csv",
        )

    def import_data(self, body=None):
        return {
            "section": self.section.pk,
            "academic_year": "2026-2027",
            "term": CourseOffering.Term.FALL,
            "file": self.csv_upload(body),
        }

    def create_preview(self, body=None):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("student_onboarding:upload"),
            self.import_data(body),
        )

        self.assertEqual(response.status_code, 302)

        return StudentImportBatch.objects.latest("pk")

    def confirm_batch(self, batch):
        return self.client.post(
            reverse(
                "student_onboarding:confirm",
                args=[batch.pk],
            )
        )

    def provision_two_students(self):
        batch = self.create_preview()
        response = self.confirm_batch(batch)

        self.assertEqual(response.status_code, 302)

        batch.refresh_from_db()

        self.assertEqual(
            batch.status,
            StudentImportBatch.Status.CONFIRMED,
        )

        return batch

    def test_admin_can_open_dashboard(self):
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("student_onboarding:dashboard")
        )

        self.assertEqual(response.status_code, 200)

    def test_student_cannot_upload_accounts(self):
        self.client.force_login(self.student)

        response = self.client.post(
            reverse("student_onboarding:upload"),
            self.import_data(),
        )

        self.assertEqual(response.status_code, 403)

        self.assertEqual(
            StudentImportBatch.objects.count(),
            0,
        )

    def test_teacher_cannot_upload_accounts(self):
        self.client.force_login(self.teacher)

        response = self.client.post(
            reverse("student_onboarding:upload"),
            self.import_data(),
        )

        self.assertEqual(response.status_code, 403)

    def test_preview_does_not_create_users(self):
        batch = self.create_preview()

        self.assertEqual(batch.row_count, 2)
        self.assertEqual(batch.error_count, 0)

        self.assertFalse(
            User.objects.filter(
                username="2026-SE-001"
            ).exists()
        )

    def test_confirm_creates_inactive_accounts(self):
        batch = self.provision_two_students()

        user = User.objects.get(
            username="2026-SE-001"
        )

        self.assertFalse(user.is_active)
        self.assertFalse(user.has_usable_password())

        self.assertTrue(
            UserProfile.objects.filter(
                user=user,
                role=UserProfile.Role.STUDENT,
            ).exists()
        )

        self.assertEqual(
            StudentIdentity.objects.filter(
                import_batch=batch
            ).count(),
            2,
        )

        self.assertEqual(
            CourseEnrollment.objects.filter(
                student=user
            ).count(),
            0,
        )

    def test_confirm_twice_cannot_duplicate_accounts(self):
        batch = self.provision_two_students()

        response = self.confirm_batch(batch)

        self.assertEqual(response.status_code, 302)

        self.assertEqual(
            User.objects.filter(
                username="2026-SE-001"
            ).count(),
            1,
        )

    def test_duplicate_email_is_rejected(self):
        body = (
            "roll_number,first_name,last_name,email\n"
            "2026-SE-001,Ali,Ahmed,existing@uni.edu\n"
        )

        batch = self.create_preview(body)

        self.assertGreater(
            batch.error_count,
            0,
        )

        response = self.confirm_batch(batch)

        self.assertEqual(response.status_code, 302)

        self.assertFalse(
            User.objects.filter(
                username="2026-SE-001"
            ).exists()
        )

    def test_duplicate_roll_number_in_file(self):
        body = (
            "roll_number,first_name,last_name,email\n"
            "2026-SE-001,Ali,Ahmed,ali@uni.edu\n"
            "2026-SE-001,Hassan,Raza,hassan@uni.edu\n"
        )

        batch = self.create_preview(body)

        self.assertGreater(batch.error_count, 0)

    def test_email_domain_restriction(self):
        body = (
            "roll_number,first_name,last_name,email\n"
            "2026-SE-001,Ali,Ahmed,ali@other.com\n"
        )

        batch = self.create_preview(body)

        self.assertEqual(batch.error_count, 1)

    def test_activation_email_can_be_sent(self):
        batch = self.provision_two_students()

        result = send_pending_activation_emails(
            batch.pk,
            limit=2,
        )

        self.assertEqual(result.sent, 2)
        self.assertEqual(len(mail.outbox), 2)

        self.assertIn(
            "Activate your AssignHub",
            mail.outbox[0].subject,
        )

    def test_activation_creates_password_and_enrollment(self):
        batch = self.provision_two_students()

        identity = StudentIdentity.objects.get(
            roll_number="2026-SE-001"
        )

        token = make_activation_token(identity)

        self.client.logout()

        response = self.client.post(
            reverse(
                "student_onboarding:activate",
                kwargs={"token": token},
            ),
            {
                "new_password1": "Strong#AcademicPass8642",
                "new_password2": "Strong#AcademicPass8642",
            },
        )

        self.assertEqual(response.status_code, 302)

        identity.refresh_from_db()
        identity.user.refresh_from_db()

        self.assertEqual(
            identity.status,
            StudentIdentity.Status.ACTIVE,
        )

        self.assertTrue(identity.user.is_active)

        self.assertTrue(
            identity.user.check_password(
                "Strong#AcademicPass8642"
            )
        )

        self.assertTrue(
            StudentClassAllocation.objects.filter(
                student=identity.user,
                section=self.section,
                status=StudentClassAllocation.Status.ACTIVE,
            ).exists()
        )

        self.assertTrue(
            CourseEnrollment.objects.filter(
                student=identity.user,
                offering=self.offering,
                status=CourseEnrollment.Status.ACTIVE,
            ).exists()
        )

    def test_activation_link_cannot_be_reused(self):
        self.provision_two_students()

        identity = StudentIdentity.objects.get(
            roll_number="2026-SE-001"
        )

        token = make_activation_token(identity)

        url = reverse(
            "student_onboarding:activate",
            kwargs={"token": token},
        )

        self.client.logout()

        response = self.client.post(
            url,
            {
                "new_password1": "Strong#AcademicPass8642",
                "new_password2": "Strong#AcademicPass8642",
            },
        )

        self.assertEqual(response.status_code, 302)

        second_response = self.client.get(url)

        self.assertEqual(
            second_response.status_code,
            400,
        )

    def test_mismatched_passwords_do_not_activate(self):
        self.provision_two_students()

        identity = StudentIdentity.objects.get(
            roll_number="2026-SE-001"
        )

        token = make_activation_token(identity)

        self.client.logout()

        response = self.client.post(
            reverse(
                "student_onboarding:activate",
                kwargs={"token": token},
            ),
            {
                "new_password1": "Strong#AcademicPass8642",
                "new_password2": "Different#AcademicPass8642",
            },
        )

        self.assertEqual(response.status_code, 200)

        identity.user.refresh_from_db()

        self.assertFalse(identity.user.is_active)
        self.assertFalse(
            identity.user.has_usable_password()
        )

    def test_invalid_token_is_rejected(self):
        response = self.client.get(
            reverse(
                "student_onboarding:activate",
                kwargs={"token": "invalid-token"},
            )
        )

        self.assertEqual(response.status_code, 400)

    def test_capacity_validation_prevents_partial_import(self):
        self.section.capacity = 1
        self.section.save(
            update_fields=["capacity"]
        )

        batch = self.create_preview()

        response = self.confirm_batch(batch)

        self.assertEqual(response.status_code, 302)

        self.assertFalse(
            User.objects.filter(
                username="2026-SE-001"
            ).exists()
        )

        self.assertFalse(
            User.objects.filter(
                username="2026-SE-002"
            ).exists()
        )

    def test_download_sample_requires_admin(self):
        self.client.force_login(self.student)

        response = self.client.get(
            reverse("student_onboarding:sample")
        )

        self.assertEqual(response.status_code, 403)