import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from departments.models import Department, Program
from semesters.models import Semester, Section

from .forms import (
    AssignmentForm,
    GradeSubmissionForm,
    SubmissionForm,
)
from courses.models import (
    Course,
    CourseOffering,
    CourseEnrollment,
)
from .models import Assignment, Submission
from .permissions import is_admin, is_student, is_teacher


User = get_user_model()


# ============================================================
# TEST DATA HELPERS
# ============================================================

def future_date(days=7):
    return timezone.now() + timedelta(days=days)


def past_date(days=1):
    return timezone.now() - timedelta(days=days)


def deadline_input(value):
    return timezone.localtime(value).strftime(
        "%Y-%m-%dT%H:%M"
    )


def valid_pdf(filename="document.pdf"):
    return SimpleUploadedFile(
        filename,
        b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF",
        content_type="application/pdf",
    )


def invalid_pdf(filename="document.pdf"):
    return SimpleUploadedFile(
        filename,
        b"This is not a valid PDF file",
        content_type="application/pdf",
    )


def create_user(username, role, is_staff=False):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="StrongPassword123!",
        is_staff=is_staff,
    )

    UserProfile.objects.create(
        user=user,
        role=role,
    )

    return user


def assignment_data(**overrides):
    data = {
        "title": "Software Engineering Assignment",
        "instructions": "Explain software development models.",
        "deadline": deadline_input(future_date()),
        "total_marks": 100,
        "rubric": "Clarity and correctness",
        "status": Assignment.Status.PUBLISHED,
    }

    data.update(overrides)
    return data


# ============================================================
# COMMON TEST FIXTURE
# ============================================================

class AssignmentTestBase(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls._temp_media = tempfile.mkdtemp(
            prefix="assignhub_test_media_"
        )

        cls._media_override = override_settings(
            MEDIA_ROOT=cls._temp_media,
        )

        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media_override.disable()

        shutil.rmtree(
            cls._temp_media,
            ignore_errors=True,
        )

        super().tearDownClass()

    def setUp(self):

        self.teacher = create_user(
            "teacher_one",
            UserProfile.Role.TEACHER,
        )

        self.teacher2 = create_user(
            "teacher_two",
            UserProfile.Role.TEACHER,
            is_staff=True,
        )

        self.student = create_user(
            "student_one",
            UserProfile.Role.STUDENT,
        )

        self.student2 = create_user(
            "student_two",
            UserProfile.Role.STUDENT,
        )

        self.admin = User.objects.create_superuser(
            username="admin_user",
            email="admin@example.com",
            password="StrongAdminPassword123!",
        )

        # Real academic hierarchy. Every published assignment must
        # belong to an offering taught by its creator.
        self.department = Department.objects.create(
            code="CS-TEST",
            name="Computer Science Test Department",
        )
        self.program = Program.objects.create(
            department=self.department,
            code="BSCS-TEST",
            name="BS Computer Science Test",
            duration_semesters=8,
        )
        self.semester = Semester.objects.create(
            program=self.program,
            number=1,
        )
        self.section = Section.objects.create(
            semester=self.semester,
            code="A",
        )
        self.other_section = Section.objects.create(
            semester=self.semester,
            code="B",
        )
        self.course = Course.objects.create(
            program=self.program,
            semester=self.semester,
            code="CS101",
            title="Python Fundamentals",
            credit_hours=3,
        )
        self.other_course = Course.objects.create(
            program=self.program,
            semester=self.semester,
            code="CS102",
            title="Database Systems",
            credit_hours=3,
        )
        self.offering = CourseOffering.objects.create(
            course=self.course,
            section=self.section,
            teacher=self.teacher,
            academic_year="2026-2027",
            term=CourseOffering.Term.FALL,
        )
        self.other_offering = CourseOffering.objects.create(
            course=self.other_course,
            section=self.other_section,
            teacher=self.teacher2,
            academic_year="2026-2027",
            term=CourseOffering.Term.FALL,
        )
        # Both authorized students can submit to the primary offering;
        # the other teacher's offering remains separate.
        self.enrollment = CourseEnrollment.objects.create(
            offering=self.offering,
            student=self.student,
            status=CourseEnrollment.Status.ACTIVE,
        )
        self.enrollment2 = CourseEnrollment.objects.create(
            offering=self.offering,
            student=self.student2,
            status=CourseEnrollment.Status.ACTIVE,
        )

        self.assignment = Assignment.objects.create(
            title="Python Assignment",
            instructions="Explain Python decorators.",
            deadline=future_date(),
            total_marks=100,
            rubric="Correctness",
            status=Assignment.Status.PUBLISHED,
            created_by=self.teacher,
            course_offering=self.offering,
        )

        self.other_assignment = Assignment.objects.create(
            title="Database Assignment",
            instructions="Explain database normalization.",
            deadline=future_date(),
            total_marks=50,
            status=Assignment.Status.PUBLISHED,
            created_by=self.teacher2,
            course_offering=self.other_offering,
        )

    def assignment_data(self, **overrides):
        """A valid teacher-owned offering is required for publication."""
        data = assignment_data(course_offering=self.offering.pk)
        data.update(overrides)
        return data

    def login_as(self, user):
        self.client.force_login(user)

    def make_assignment(
        self,
        owner=None,
        status=Assignment.Status.PUBLISHED,
        deadline=None,
        total_marks=100,
    ):
        return Assignment.objects.create(
            title="Additional Assignment",
            instructions="Complete the task.",
            deadline=deadline or future_date(),
            total_marks=total_marks,
            status=status,
            created_by=owner or self.teacher,
            course_offering=(
                self.other_offering
                if owner and owner.pk == self.teacher2.pk
                else self.offering
            ),
        )

    def make_submission(
        self,
        assignment=None,
        student=None,
        status=Submission.Status.SUBMITTED,
        text="This is my assignment answer.",
        marks=None,
        feedback="",
    ):
        submitted_at = (
            timezone.now()
            if status != Submission.Status.DRAFT
            else None
        )

        return Submission.objects.create(
            assignment=assignment or self.assignment,
            student=student or self.student,
            text_content=text,
            status=status,
            submitted_at=submitted_at,
            marks=marks,
            feedback=feedback,
        )

    def submit_url(self, assignment=None):
        return reverse(
            "assignments:submit",
            args=[(assignment or self.assignment).pk],
        )

    def detail_url(self, assignment=None):
        return reverse(
            "assignments:detail",
            args=[(assignment or self.assignment).pk],
        )

    def review_url(self, submission):
        return reverse(
            "assignments:submission_review",
            args=[submission.pk],
        )

    def file_url(self, submission):
        return reverse(
            "assignments:submission_file",
            args=[submission.pk],
        )


# ============================================================
# 1. ROLE AND PERMISSION TESTS
# ============================================================

class RolePermissionTests(AssignmentTestBase):

    def test_teacher_role_recognized(self):
        self.assertTrue(is_teacher(self.teacher))

    def test_staff_teacher_recognized(self):
        self.assertTrue(is_teacher(self.teacher2))

    def test_student_role_recognized(self):
        self.assertTrue(is_student(self.student))

    def test_admin_role_recognized(self):
        self.assertTrue(is_admin(self.admin))

    def test_student_is_not_teacher(self):
        self.assertFalse(is_teacher(self.student))

    def test_teacher_is_not_student(self):
        self.assertFalse(is_student(self.teacher))

    def test_teacher_is_not_admin(self):
        self.assertFalse(is_admin(self.teacher))

    def test_student_is_not_admin(self):
        self.assertFalse(is_admin(self.student))

    def test_anonymous_has_no_roles(self):
        anonymous = AnonymousUser()

        self.assertFalse(is_teacher(anonymous))
        self.assertFalse(is_student(anonymous))
        self.assertFalse(is_admin(anonymous))

    def test_inactive_teacher_has_no_permissions(self):
        self.teacher.is_active = False
        self.teacher.save()

        self.assertFalse(is_teacher(self.teacher))

    def test_inactive_student_has_no_permissions(self):
        self.student.is_active = False
        self.student.save()

        self.assertFalse(is_student(self.student))

    def test_user_without_profile_has_no_teacher_role(self):
        user = User.objects.create_user(
            username="no_profile",
            password="StrongPassword123!",
        )

        self.assertFalse(is_teacher(user))

    def test_staff_without_teacher_role_is_not_teacher(self):
        self.assertFalse(is_teacher(self.admin))


# ============================================================
# 2. ASSIGNMENT LIST TESTS
# ============================================================

class AssignmentListTests(AssignmentTestBase):

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(
            reverse("assignments:list")
        )

        self.assertEqual(response.status_code, 302)

    def test_teacher_can_open_assignment_list(self):
        self.login_as(self.teacher)

        response = self.client.get(
            reverse("assignments:list")
        )

        self.assertEqual(response.status_code, 200)

    def test_teacher_sees_own_assignment(self):
        self.login_as(self.teacher)

        response = self.client.get(
            reverse("assignments:list")
        )

        self.assertContains(
            response,
            "Python Assignment",
        )

    def test_teacher_cannot_see_other_teacher_assignment(self):
        self.login_as(self.teacher)

        response = self.client.get(
            reverse("assignments:list")
        )

        self.assertNotContains(
            response,
            "Database Assignment",
        )

    def test_student_sees_published_assignments(self):
        self.login_as(self.student)

        response = self.client.get(
            reverse("assignments:list")
        )

        self.assertContains(
            response,
            "Python Assignment",
        )

    def test_student_cannot_see_draft_assignments(self):
        self.make_assignment(
            status=Assignment.Status.DRAFT
        )

        self.login_as(self.student)

        response = self.client.get(
            reverse("assignments:list")
        )

        self.assertEqual(
            response.context["assignments"].filter(
                status=Assignment.Status.DRAFT
            ).count(),
            0,
        )

    def test_student_cannot_see_closed_assignments(self):
        self.make_assignment(
            status=Assignment.Status.CLOSED
        )

        self.login_as(self.student)

        response = self.client.get(
            reverse("assignments:list")
        )

        self.assertFalse(
            response.context["assignments"].filter(
                status=Assignment.Status.CLOSED
            ).exists()
        )

    def test_admin_can_see_all_assignments(self):
        self.login_as(self.admin)

        response = self.client.get(
            reverse("assignments:list")
        )

        self.assertContains(
            response,
            "Python Assignment",
        )

        self.assertContains(
            response,
            "Database Assignment",
        )

    def test_student_does_not_get_create_button(self):
        self.login_as(self.student)

        response = self.client.get(
            reverse("assignments:list")
        )

        self.assertFalse(
            response.context["can_create"]
        )

    def test_teacher_gets_create_permission(self):
        self.login_as(self.teacher)

        response = self.client.get(
            reverse("assignments:list")
        )

        self.assertTrue(
            response.context["can_create"]
        )


# ============================================================
# 3. ASSIGNMENT DETAIL TESTS
# ============================================================

class AssignmentDetailTests(AssignmentTestBase):

    def test_owner_can_view_assignment(self):
        self.login_as(self.teacher)

        response = self.client.get(
            self.detail_url()
        )

        self.assertEqual(response.status_code, 200)

    def test_other_teacher_cannot_view_assignment(self):
        self.login_as(self.teacher2)

        response = self.client.get(
            self.detail_url()
        )

        self.assertEqual(response.status_code, 403)

    def test_student_can_view_published_assignment(self):
        self.login_as(self.student)

        response = self.client.get(
            self.detail_url()
        )

        self.assertEqual(response.status_code, 200)

    def test_student_cannot_view_draft_assignment(self):
        self.assignment.status = Assignment.Status.DRAFT
        self.assignment.save()

        self.login_as(self.student)

        response = self.client.get(
            self.detail_url()
        )

        self.assertEqual(response.status_code, 403)

    def test_student_cannot_view_closed_assignment(self):
        self.assignment.status = Assignment.Status.CLOSED
        self.assignment.save()

        self.login_as(self.student)

        response = self.client.get(
            self.detail_url()
        )

        self.assertEqual(response.status_code, 403)

    def test_admin_can_view_assignment(self):
        self.login_as(self.admin)

        response = self.client.get(
            self.detail_url()
        )

        self.assertEqual(response.status_code, 200)

    def test_anonymous_cannot_view_assignment(self):
        response = self.client.get(
            self.detail_url()
        )

        self.assertEqual(response.status_code, 302)

    def test_nonexistent_assignment_returns_404(self):
        self.login_as(self.teacher)

        response = self.client.get(
            reverse("assignments:detail", args=[999999])
        )

        self.assertEqual(response.status_code, 404)

    def test_student_only_gets_own_submission(self):
        self.make_submission(student=self.student2)

        self.login_as(self.student)

        response = self.client.get(
            self.detail_url()
        )

        self.assertIsNone(
            response.context["submission"]
        )


# ============================================================
# 4. ASSIGNMENT CREATION TESTS
# ============================================================

class AssignmentCreationTests(AssignmentTestBase):

    def test_teacher_can_open_create_page(self):
        self.login_as(self.teacher)

        response = self.client.get(
            reverse("assignments:create")
        )

        self.assertEqual(response.status_code, 200)

    def test_teacher_can_create_assignment(self):
        self.login_as(self.teacher)

        response = self.client.post(
            reverse("assignments:create"),
            self.assignment_data(),
        )

        self.assertEqual(response.status_code, 302)

        self.assertTrue(
            Assignment.objects.filter(
                title="Software Engineering Assignment",
                created_by=self.teacher,
            ).exists()
        )

    def test_student_cannot_create_assignment(self):
        self.login_as(self.student)

        response = self.client.post(
            reverse("assignments:create"),
            self.assignment_data(),
        )

        self.assertEqual(response.status_code, 403)

    def test_admin_cannot_create_teacher_assignment(self):
        self.login_as(self.admin)

        response = self.client.post(
            reverse("assignments:create"),
            self.assignment_data(),
        )

        self.assertEqual(response.status_code, 403)

    def test_anonymous_cannot_create_assignment(self):
        response = self.client.post(
            reverse("assignments:create"),
            self.assignment_data(),
        )

        self.assertEqual(response.status_code, 302)

    def test_empty_title_rejected(self):
        self.login_as(self.teacher)

        response = self.client.post(
            reverse("assignments:create"),
            self.assignment_data(title=""),
        )

        self.assertEqual(response.status_code, 200)

        self.assertTrue(
            response.context["form"].errors
        )

    def test_empty_instructions_rejected(self):
        self.login_as(self.teacher)

        response = self.client.post(
            reverse("assignments:create"),
            self.assignment_data(instructions=""),
        )

        self.assertEqual(response.status_code, 200)

        self.assertIn(
            "instructions",
            response.context["form"].errors,
        )

    def test_zero_total_marks_rejected(self):
        self.login_as(self.teacher)

        response = self.client.post(
            reverse("assignments:create"),
            self.assignment_data(total_marks=0),
        )

        self.assertEqual(response.status_code, 200)

        self.assertIn(
            "total_marks",
            response.context["form"].errors,
        )

    def test_negative_total_marks_rejected(self):
        self.login_as(self.teacher)

        response = self.client.post(
            reverse("assignments:create"),
            self.assignment_data(total_marks=-10),
        )

        self.assertEqual(response.status_code, 200)

        self.assertIn(
            "total_marks",
            response.context["form"].errors,
        )

    def test_invalid_status_rejected(self):
        self.login_as(self.teacher)

        response = self.client.post(
            reverse("assignments:create"),
            self.assignment_data(status="HACKED"),
        )

        self.assertEqual(response.status_code, 200)

        self.assertIn(
            "status",
            response.context["form"].errors,
        )

    def test_missing_deadline_rejected(self):
        self.login_as(self.teacher)

        response = self.client.post(
            reverse("assignments:create"),
            self.assignment_data(deadline=""),
        )

        self.assertEqual(response.status_code, 200)

        self.assertIn(
            "deadline",
            response.context["form"].errors,
        )

    def test_created_by_cannot_be_forged(self):
        self.login_as(self.teacher)

        data = self.assignment_data(
            created_by=self.teacher2.pk
        )

        response = self.client.post(
            reverse("assignments:create"),
            data,
        )

        self.assertEqual(response.status_code, 302)

        assignment = Assignment.objects.get(
            title="Software Engineering Assignment"
        )

        self.assertEqual(
            assignment.created_by,
            self.teacher,
        )

    def test_default_draft_assignment_model(self):
        assignment = Assignment.objects.create(
            title="Draft Test",
            instructions="Test",
            deadline=future_date(),
            created_by=self.teacher,
        )

        self.assertEqual(
            assignment.status,
            Assignment.Status.DRAFT,
        )
    def test_past_deadline_rejected_on_creation(self):
        self.login_as(self.teacher)

        response = self.client.post(
            reverse("assignments:create"),
            self.assignment_data(
                deadline=deadline_input(
                    past_date()
                ),
            ),
        )

        self.assertEqual(response.status_code, 200)

        self.assertIn(
            "deadline",
            response.context["form"].errors,
        )

        self.assertFalse(
            Assignment.objects.filter(
                title="Software Engineering Assignment",
                created_by=self.teacher,
            ).exists()
        )

    def test_current_deadline_rejected_on_creation(self):
        self.login_as(self.teacher)

        response = self.client.post(
            reverse("assignments:create"),
            self.assignment_data(
                deadline=deadline_input(
                    timezone.now()
                ),
            ),
        )

        self.assertEqual(response.status_code, 200)

        self.assertIn(
            "deadline",
            response.context["form"].errors,
        )

    def test_future_deadline_accepted_on_creation(self):
        self.login_as(self.teacher)

        response = self.client.post(
            reverse("assignments:create"),
            self.assignment_data(
                deadline=deadline_input(
                    future_date(days=3)
                ),
            ),
        )

        self.assertEqual(response.status_code, 302)

        self.assertTrue(
            Assignment.objects.filter(
                title="Software Engineering Assignment",
                created_by=self.teacher,
            ).exists()
        )

# ============================================================
# 5. ASSIGNMENT EDIT TESTS
# ============================================================

class AssignmentEditTests(AssignmentTestBase):

    def edit_url(self):
        return reverse(
            "assignments:edit",
            args=[self.assignment.pk],
        )

    def test_owner_can_open_edit_page(self):
        self.login_as(self.teacher)

        response = self.client.get(
            self.edit_url()
        )

        self.assertEqual(response.status_code, 200)

    def test_owner_can_edit_assignment(self):
        self.login_as(self.teacher)

        response = self.client.post(
            self.edit_url(),
            self.assignment_data(
                title="Updated Assignment Title"
            ),
        )

        self.assertEqual(response.status_code, 302)

        self.assignment.refresh_from_db()

        self.assertEqual(
            self.assignment.title,
            "Updated Assignment Title",
        )

    def test_other_teacher_cannot_edit(self):
        self.login_as(self.teacher2)

        response = self.client.post(
            self.edit_url(),
            self.assignment_data(title="Unauthorized Change"),
        )

        self.assertEqual(response.status_code, 403)

    def test_student_cannot_edit(self):
        self.login_as(self.student)

        response = self.client.post(
            self.edit_url(),
            self.assignment_data(),
        )

        self.assertEqual(response.status_code, 403)

    def test_admin_cannot_edit_teacher_assignment(self):
        self.login_as(self.admin)

        response = self.client.post(
            self.edit_url(),
            self.assignment_data(),
        )

        self.assertEqual(response.status_code, 403)

    def test_cannot_edit_after_final_submission(self):
        self.make_submission()

        self.login_as(self.teacher)

        response = self.client.post(
            self.edit_url(),
            self.assignment_data(
                title="Changed After Submission"
            ),
        )

        self.assertEqual(response.status_code, 403)

    def test_cannot_edit_after_grading(self):
        self.make_submission(
            status=Submission.Status.GRADED,
            marks=Decimal("80.00"),
        )

        self.login_as(self.teacher)

        response = self.client.post(
            self.edit_url(),
            self.assignment_data(),
        )

        self.assertEqual(response.status_code, 403)

    def test_invalid_edit_does_not_change_title(self):
        self.login_as(self.teacher)

        response = self.client.post(
            self.edit_url(),
            self.assignment_data(title=""),
        )

        self.assertEqual(response.status_code, 200)

        self.assignment.refresh_from_db()

        self.assertEqual(
            self.assignment.title,
            "Python Assignment",
        )

    def test_cannot_change_deadline_to_past_date(self):
        self.login_as(self.teacher)

        response = self.client.post(
            self.edit_url(),
            self.assignment_data(
                deadline=deadline_input(
                    past_date()
                ),
            ),
        )

        self.assertEqual(response.status_code, 200)

        self.assertIn(
            "deadline",
            response.context["form"].errors,
        )

        self.assignment.refresh_from_db()

        self.assertGreater(
            self.assignment.deadline,
            timezone.now(),
        )
# ============================================================
# 6. ASSIGNMENT DELETION TESTS
# ============================================================

class AssignmentDeleteTests(AssignmentTestBase):

    def delete_url(self):
        return reverse(
            "assignments:delete",
            args=[self.assignment.pk],
        )

    def test_owner_can_open_delete_confirmation(self):
        self.login_as(self.teacher)

        response = self.client.get(
            self.delete_url()
        )

        self.assertEqual(response.status_code, 200)

    def test_get_request_does_not_delete(self):
        self.login_as(self.teacher)

        self.client.get(self.delete_url())

        self.assertTrue(
            Assignment.objects.filter(
                pk=self.assignment.pk
            ).exists()
        )

    def test_owner_can_delete_without_submissions(self):
        assignment_id = self.assignment.pk

        self.login_as(self.teacher)

        response = self.client.post(
            self.delete_url()
        )

        self.assertEqual(response.status_code, 302)

        self.assertFalse(
            Assignment.objects.filter(
                pk=assignment_id
            ).exists()
        )

    def test_student_cannot_delete(self):
        self.login_as(self.student)

        response = self.client.post(
            self.delete_url()
        )

        self.assertEqual(response.status_code, 403)

    def test_other_teacher_cannot_delete(self):
        self.login_as(self.teacher2)

        response = self.client.post(
            self.delete_url()
        )

        self.assertEqual(response.status_code, 403)

    def test_admin_cannot_delete_teacher_assignment(self):
        self.login_as(self.admin)

        response = self.client.post(
            self.delete_url()
        )

        self.assertEqual(response.status_code, 403)

    def test_cannot_delete_with_final_submission(self):
        self.make_submission()

        self.login_as(self.teacher)

        response = self.client.post(
            self.delete_url()
        )

        self.assertEqual(response.status_code, 403)

        self.assertTrue(
            Assignment.objects.filter(
                pk=self.assignment.pk
            ).exists()
        )

    def test_cannot_delete_with_draft_submission(self):
        self.make_submission(
            status=Submission.Status.DRAFT,
            text="Draft answer",
        )

        self.login_as(self.teacher)

        response = self.client.post(
            self.delete_url()
        )

        self.assertEqual(response.status_code, 403)


# ============================================================
# 7. STUDENT SUBMISSION TESTS
# ============================================================

class StudentSubmissionTests(AssignmentTestBase):

    def test_student_can_open_submission_form(self):
        self.login_as(self.student)

        response = self.client.get(
            self.submit_url()
        )

        self.assertEqual(response.status_code, 200)

    def test_student_can_submit_text(self):
        self.login_as(self.student)

        response = self.client.post(
            self.submit_url(),
            {
                "text_content": (
                    "This is my final Python assignment."
                ),
            },
        )

        self.assertEqual(response.status_code, 302)

        submission = Submission.objects.get(
            assignment=self.assignment,
            student=self.student,
        )

        self.assertEqual(
            submission.status,
            Submission.Status.SUBMITTED,
        )

        self.assertIsNotNone(
            submission.submitted_at
        )

    def test_student_can_submit_pdf(self):
        self.login_as(self.student)

        response = self.client.post(
            self.submit_url(),
            {
                "text_content": "",
                "submission_file": valid_pdf(),
            },
        )

        self.assertEqual(response.status_code, 302)

        submission = Submission.objects.get(
            assignment=self.assignment,
            student=self.student,
        )

        self.assertTrue(submission.submission_file)

    def test_student_can_submit_text_and_pdf(self):
        self.login_as(self.student)

        response = self.client.post(
            self.submit_url(),
            {
                "text_content": "My written answer",
                "submission_file": valid_pdf(),
            },
        )

        self.assertEqual(response.status_code, 302)

        submission = Submission.objects.get(
            assignment=self.assignment,
            student=self.student,
        )

        self.assertTrue(submission.text_content)
        self.assertTrue(submission.submission_file)

    def test_empty_submission_rejected(self):
        self.login_as(self.student)

        response = self.client.post(
            self.submit_url(),
            {
                "text_content": "",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertFalse(
            Submission.objects.filter(
                assignment=self.assignment,
                student=self.student,
            ).exists()
        )

    def test_whitespace_only_submission_rejected(self):
        self.login_as(self.student)

        response = self.client.post(
            self.submit_url(),
            {
                "text_content": "   \n   ",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertTrue(
            response.context["form"].errors
        )

    def test_duplicate_final_submission_blocked(self):
        self.make_submission()

        self.login_as(self.student)

        response = self.client.post(
            self.submit_url(),
            {
                "text_content": "Second submission",
            },
        )

        self.assertEqual(response.status_code, 403)

        self.assertEqual(
            Submission.objects.filter(
                assignment=self.assignment,
                student=self.student,
            ).count(),
            1,
        )

    def test_graded_submission_cannot_be_replaced(self):
        submission = self.make_submission(
            status=Submission.Status.GRADED,
            marks=Decimal("90.00"),
        )

        self.login_as(self.student)

        response = self.client.post(
            self.submit_url(),
            {
                "text_content": "Attempt to replace answer",
            },
        )

        self.assertEqual(response.status_code, 403)

        submission.refresh_from_db()

        self.assertEqual(
            submission.marks,
            Decimal("90.00"),
        )

    def test_draft_can_be_finalized(self):
        draft = self.make_submission(
            status=Submission.Status.DRAFT,
            text="Draft text",
        )

        self.login_as(self.student)

        response = self.client.post(
            self.submit_url(),
            {
                "text_content": "Final answer",
            },
        )

        self.assertEqual(response.status_code, 302)

        draft.refresh_from_db()

        self.assertEqual(
            draft.status,
            Submission.Status.SUBMITTED,
        )

        self.assertEqual(
            draft.text_content,
            "Final answer",
        )

    def test_teacher_cannot_submit(self):
        self.login_as(self.teacher)

        response = self.client.post(
            self.submit_url(),
            {
                "text_content": "Teacher submission",
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_admin_cannot_submit(self):
        self.login_as(self.admin)

        response = self.client.post(
            self.submit_url(),
            {
                "text_content": "Admin submission",
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_anonymous_cannot_submit(self):
        response = self.client.post(
            self.submit_url(),
            {
                "text_content": "Anonymous submission",
            },
        )

        self.assertEqual(response.status_code, 302)

    def test_cannot_submit_draft_assignment(self):
        self.assignment.status = Assignment.Status.DRAFT
        self.assignment.save()

        self.login_as(self.student)

        response = self.client.post(
            self.submit_url(),
            {
                "text_content": "Answer",
            },
        )

        self.assertEqual(response.status_code, 404)

    def test_cannot_submit_closed_assignment(self):
        self.assignment.status = Assignment.Status.CLOSED
        self.assignment.save()

        self.login_as(self.student)

        response = self.client.post(
            self.submit_url(),
            {
                "text_content": "Answer",
            },
        )

        self.assertEqual(response.status_code, 404)

    def test_cannot_submit_after_deadline(self):
        self.assignment.deadline = past_date()
        self.assignment.save()

        self.login_as(self.student)

        response = self.client.post(
            self.submit_url(),
            {
                "text_content": "Late answer",
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_submitted_at_is_server_generated(self):
        self.login_as(self.student)

        fake_time = "2000-01-01T00:00:00"

        response = self.client.post(
            self.submit_url(),
            {
                "text_content": "My answer",
                "submitted_at": fake_time,
            },
        )

        self.assertEqual(response.status_code, 302)

        submission = Submission.objects.get(
            student=self.student,
            assignment=self.assignment,
        )

        self.assertGreater(
            submission.submitted_at,
            timezone.now() - timedelta(minutes=2),
        )

    def test_student_cannot_forge_marks(self):
        self.login_as(self.student)

        response = self.client.post(
            self.submit_url(),
            {
                "text_content": "My answer",
                "marks": "100",
                "status": Submission.Status.GRADED,
                "feedback": "Excellent",
            },
        )

        self.assertEqual(response.status_code, 302)

        submission = Submission.objects.get(
            student=self.student,
            assignment=self.assignment,
        )

        self.assertIsNone(submission.marks)
        self.assertEqual(submission.feedback, "")

        self.assertEqual(
            submission.status,
            Submission.Status.SUBMITTED,
        )

    def test_student_cannot_forge_assignment(self):
        self.login_as(self.student)

        response = self.client.post(
            self.submit_url(),
            {
                "text_content": "My answer",
                "assignment": self.other_assignment.pk,
            },
        )

        self.assertEqual(response.status_code, 302)

        submission = Submission.objects.get(
            student=self.student,
            assignment=self.assignment,
        )

        self.assertEqual(
            submission.assignment,
            self.assignment,
        )

    def test_student_cannot_forge_student_id(self):
        self.login_as(self.student)

        response = self.client.post(
            self.submit_url(),
            {
                "text_content": "My answer",
                "student": self.student2.pk,
            },
        )

        self.assertEqual(response.status_code, 302)

        submission = Submission.objects.get(
            assignment=self.assignment,
            student=self.student,
        )

        self.assertEqual(
            submission.student,
            self.student,
        )


# ============================================================
# 8. SUBMISSION LIST SECURITY
# ============================================================

class SubmissionListTests(AssignmentTestBase):

    def test_teacher_sees_own_submissions(self):
        self.make_submission()

        self.login_as(self.teacher)

        response = self.client.get(
            reverse("assignments:submissions")
        )

        self.assertContains(
            response,
            self.student.username,
        )

    def test_teacher_cannot_see_other_teacher_submissions(self):
        self.make_submission(
            assignment=self.other_assignment
        )

        self.login_as(self.teacher)

        response = self.client.get(
            reverse("assignments:submissions")
        )

        self.assertNotContains(
            response,
            "Database Assignment",
        )

    def test_student_sees_own_submissions(self):
        self.make_submission()

        self.login_as(self.student)

        response = self.client.get(
            reverse("assignments:submissions")
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.context["submissions"].count(),
            1,
        )

    def test_student_cannot_see_other_student_submission(self):
        self.make_submission(student=self.student2)

        self.login_as(self.student)

        response = self.client.get(
            reverse("assignments:submissions")
        )

        self.assertEqual(
            response.context["submissions"].count(),
            0,
        )

    def test_admin_can_view_all_submissions(self):
        self.make_submission()

        self.make_submission(
            assignment=self.other_assignment,
            student=self.student2,
        )

        self.login_as(self.admin)

        response = self.client.get(
            reverse("assignments:submissions")
        )

        self.assertEqual(
            response.context["submissions"].count(),
            2,
        )

    def test_anonymous_cannot_view_submissions(self):
        response = self.client.get(
            reverse("assignments:submissions")
        )

        self.assertEqual(response.status_code, 302)


# ============================================================
# 9. GRADING TESTS
# ============================================================

class GradingTests(AssignmentTestBase):

    def setUp(self):
        super().setUp()

        self.submission = self.make_submission()

    def test_owner_teacher_can_open_review(self):
        self.login_as(self.teacher)

        response = self.client.get(
            self.review_url(self.submission)
        )

        self.assertEqual(response.status_code, 200)

    def test_owner_teacher_can_grade(self):
        self.login_as(self.teacher)

        response = self.client.post(
            self.review_url(self.submission),
            {
                "marks": "85.50",
                "feedback": "Good work",
            },
        )

        self.assertEqual(response.status_code, 302)

        self.submission.refresh_from_db()

        self.assertEqual(
            self.submission.marks,
            Decimal("85.50"),
        )

        self.assertEqual(
            self.submission.status,
            Submission.Status.GRADED,
        )

    def test_zero_marks_allowed(self):
        self.login_as(self.teacher)

        response = self.client.post(
            self.review_url(self.submission),
            {
                "marks": "0",
                "feedback": "Incomplete answer",
            },
        )

        self.assertEqual(response.status_code, 302)

        self.submission.refresh_from_db()

        self.assertEqual(
            self.submission.marks,
            Decimal("0"),
        )

    def test_full_marks_allowed(self):
        self.login_as(self.teacher)

        response = self.client.post(
            self.review_url(self.submission),
            {
                "marks": "100",
                "feedback": "Excellent",
            },
        )

        self.assertEqual(response.status_code, 302)

    def test_marks_above_total_rejected(self):
        self.login_as(self.teacher)

        response = self.client.post(
            self.review_url(self.submission),
            {
                "marks": "101",
                "feedback": "Invalid",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertIn(
            "marks",
            response.context["form"].errors,
        )

        self.submission.refresh_from_db()

        self.assertIsNone(self.submission.marks)

    def test_negative_marks_rejected(self):
        self.login_as(self.teacher)

        response = self.client.post(
            self.review_url(self.submission),
            {
                "marks": "-1",
                "feedback": "Invalid",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertIn(
            "marks",
            response.context["form"].errors,
        )

    def test_non_numeric_marks_rejected(self):
        self.login_as(self.teacher)

        response = self.client.post(
            self.review_url(self.submission),
            {
                "marks": "INVALID",
                "feedback": "Test",
            },
        )

        self.assertEqual(response.status_code, 200)

    def test_missing_marks_rejected(self):
        self.login_as(self.teacher)

        response = self.client.post(
            self.review_url(self.submission),
            {
                "marks": "",
                "feedback": "Test",
            },
        )

        self.assertEqual(response.status_code, 200)

    def test_other_teacher_cannot_grade(self):
        self.login_as(self.teacher2)

        response = self.client.post(
            self.review_url(self.submission),
            {
                "marks": "90",
                "feedback": "Unauthorized",
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_student_cannot_grade_own_submission(self):
        self.login_as(self.student)

        response = self.client.post(
            self.review_url(self.submission),
            {
                "marks": "100",
                "feedback": "Self grading",
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_admin_cannot_grade_as_teacher(self):
        self.login_as(self.admin)

        response = self.client.post(
            self.review_url(self.submission),
            {
                "marks": "90",
                "feedback": "Admin grading",
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_anonymous_cannot_grade(self):
        response = self.client.post(
            self.review_url(self.submission),
            {
                "marks": "90",
            },
        )

        self.assertEqual(response.status_code, 302)

    def test_draft_submission_cannot_be_graded(self):
        self.submission.status = Submission.Status.DRAFT
        self.submission.submitted_at = None
        self.submission.save()

        self.login_as(self.teacher)

        response = self.client.post(
            self.review_url(self.submission),
            {
                "marks": "80",
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_regrading_existing_grade(self):
        self.submission.status = Submission.Status.GRADED
        self.submission.marks = Decimal("60.00")
        self.submission.save()

        self.login_as(self.teacher)

        response = self.client.post(
            self.review_url(self.submission),
            {
                "marks": "75",
                "feedback": "Re-evaluated",
            },
        )

        self.assertEqual(response.status_code, 302)

        self.submission.refresh_from_db()

        self.assertEqual(
            self.submission.marks,
            Decimal("75"),
        )

    def test_grading_does_not_modify_student_answer(self):
        original_answer = self.submission.text_content

        self.login_as(self.teacher)

        response = self.client.post(
            self.review_url(self.submission),
            {
                "marks": "90",
                "feedback": "Good",
                "text_content": "Modified by teacher",
            },
        )

        self.assertEqual(response.status_code, 302)

        self.submission.refresh_from_db()

        self.assertEqual(
            self.submission.text_content,
            original_answer,
        )

    def test_grading_does_not_change_student(self):
        self.login_as(self.teacher)

        response = self.client.post(
            self.review_url(self.submission),
            {
                "marks": "90",
                "student": self.student2.pk,
            },
        )

        self.assertEqual(response.status_code, 302)

        self.submission.refresh_from_db()

        self.assertEqual(
            self.submission.student,
            self.student,
        )


# ============================================================
# 10. PDF VALIDATION TESTS
# ============================================================

class PDFValidationTests(AssignmentTestBase):

    def test_valid_submission_pdf_accepted(self):
        form = SubmissionForm(
            data={"text_content": ""},
            files={
                "submission_file": valid_pdf()
            },
        )

        self.assertTrue(
            form.is_valid(),
            form.errors.as_json(),
        )

    def test_fake_pdf_rejected(self):
        form = SubmissionForm(
            data={"text_content": ""},
            files={
                "submission_file": invalid_pdf()
            },
        )

        self.assertFalse(form.is_valid())

    def test_non_pdf_extension_rejected(self):
        form = SubmissionForm(
            data={"text_content": ""},
            files={
                "submission_file": SimpleUploadedFile(
                    "malware.exe",
                    b"%PDF-1.4\nTest",
                )
            },
        )

        self.assertFalse(form.is_valid())

    def test_empty_pdf_rejected(self):
        form = SubmissionForm(
            data={"text_content": ""},
            files={
                "submission_file": SimpleUploadedFile(
                    "empty.pdf",
                    b"",
                )
            },
        )

        self.assertFalse(form.is_valid())

    def test_oversized_pdf_rejected(self):
        large_file = SimpleUploadedFile(
            "large.pdf",
            b"%PDF-" + b"A" * (10 * 1024 * 1024),
        )

        form = SubmissionForm(
            data={"text_content": ""},
            files={"submission_file": large_file},
        )

        self.assertFalse(form.is_valid())

    def test_case_insensitive_pdf_extension(self):
        form = SubmissionForm(
            data={"text_content": ""},
            files={
                "submission_file": valid_pdf("FILE.PDF")
            },
        )

        self.assertTrue(
            form.is_valid(),
            form.errors.as_json(),
        )

    def test_invalid_assignment_attachment_rejected(self):
        self.login_as(self.teacher)

        response = self.client.post(
            reverse("assignments:create"),
            {
                **self.assignment_data(),
                "attachment": invalid_pdf(),
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertIn(
            "attachment",
            response.context["form"].errors,
        )

    def test_valid_assignment_attachment_accepted(self):
        self.login_as(self.teacher)

        response = self.client.post(
            reverse("assignments:create"),
            {
                **self.assignment_data(),
                "attachment": valid_pdf(),
            },
        )

        self.assertEqual(response.status_code, 302)


# ============================================================
# 11. PRIVATE FILE ACCESS TESTS
# ============================================================

class PrivateFileTests(AssignmentTestBase):

    def setUp(self):
        super().setUp()

        self.assignment.attachment = valid_pdf(
            "instructions.pdf"
        )

        self.assignment.save()

        self.submission = self.make_submission()

        self.submission.submission_file = valid_pdf(
            "student_answer.pdf"
        )

        self.submission.save()

    def assignment_file_url(self):
        return reverse(
            "assignments:attachment",
            args=[self.assignment.pk],
        )

    def test_teacher_can_download_own_attachment(self):
        self.login_as(self.teacher)

        response = self.client.get(
            self.assignment_file_url()
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.streaming)

        response.close()

    def test_student_can_download_published_attachment(self):
        self.login_as(self.student)

        response = self.client.get(
            self.assignment_file_url()
        )

        self.assertEqual(response.status_code, 200)

        response.close()

    def test_other_teacher_cannot_download_attachment(self):
        self.login_as(self.teacher2)

        response = self.client.get(
            self.assignment_file_url()
        )

        self.assertEqual(response.status_code, 403)

    def test_anonymous_cannot_download_attachment(self):
        response = self.client.get(
            self.assignment_file_url()
        )

        self.assertEqual(response.status_code, 302)

    def test_owner_student_can_download_submission(self):
        self.login_as(self.student)

        response = self.client.get(
            self.file_url(self.submission)
        )

        self.assertEqual(response.status_code, 200)

        response.close()

    def test_other_student_cannot_download_submission(self):
        self.login_as(self.student2)

        response = self.client.get(
            self.file_url(self.submission)
        )

        self.assertEqual(response.status_code, 403)

    def test_owner_teacher_can_download_submission(self):
        self.login_as(self.teacher)

        response = self.client.get(
            self.file_url(self.submission)
        )

        self.assertEqual(response.status_code, 200)

        response.close()

    def test_other_teacher_cannot_download_submission(self):
        self.login_as(self.teacher2)

        response = self.client.get(
            self.file_url(self.submission)
        )

        self.assertEqual(response.status_code, 403)

    def test_admin_can_download_submission(self):
        self.login_as(self.admin)

        response = self.client.get(
            self.file_url(self.submission)
        )

        self.assertEqual(response.status_code, 200)

        response.close()

    def test_anonymous_cannot_download_submission(self):
        response = self.client.get(
            self.file_url(self.submission)
        )

        self.assertEqual(response.status_code, 302)

    def test_missing_submission_file_returns_404(self):
        self.submission.submission_file = None
        self.submission.save()

        self.login_as(self.student)

        response = self.client.get(
            self.file_url(self.submission)
        )

        self.assertEqual(response.status_code, 404)

    def test_missing_assignment_attachment_returns_404(self):
        self.assignment.attachment = None
        self.assignment.save()

        self.login_as(self.teacher)

        response = self.client.get(
            self.assignment_file_url()
        )

        self.assertEqual(response.status_code, 404)

    def test_raw_media_url_is_not_publicly_served(self):
        self.client.logout()

        media_path = self.submission.submission_file.url

        response = self.client.get(media_path)

        self.assertEqual(response.status_code, 404)


# ============================================================
# 12. DATABASE AND MODEL INTEGRITY
# ============================================================

class ModelIntegrityTests(AssignmentTestBase):

    def test_assignment_string(self):
        self.assertEqual(
            str(self.assignment),
            "Python Assignment",
        )

    def test_assignment_is_open(self):
        self.assertTrue(
            self.assignment.is_open
        )

    def test_expired_assignment_not_open(self):
        self.assignment.deadline = past_date()
        self.assignment.save()

        self.assertFalse(
            self.assignment.is_open
        )

    def test_draft_assignment_not_open(self):
        self.assignment.status = Assignment.Status.DRAFT
        self.assignment.save()

        self.assertFalse(
            self.assignment.is_open
        )

    def test_closed_assignment_not_open(self):
        self.assignment.status = Assignment.Status.CLOSED
        self.assignment.save()

        self.assertFalse(
            self.assignment.is_open
        )

    def test_invalid_total_marks_model_validation(self):
        self.assignment.total_marks = 0

        with self.assertRaises(ValidationError):
            self.assignment.full_clean()

    def test_negative_submission_marks_rejected(self):
        submission = self.make_submission(
            marks=Decimal("-5"),
        )

        with self.assertRaises(ValidationError):
            submission.full_clean()

    def test_marks_above_assignment_total_rejected(self):
        submission = self.make_submission(
            marks=Decimal("150"),
        )

        with self.assertRaises(ValidationError):
            submission.full_clean()

    def test_valid_marks_pass_model_validation(self):
        submission = self.make_submission(
            marks=Decimal("75"),
        )

        submission.full_clean()

    def test_final_submission_requires_timestamp(self):
        submission = self.make_submission()

        submission.submitted_at = None

        with self.assertRaises(ValidationError):
            submission.full_clean()

    def test_final_submission_requires_answer(self):
        submission = self.make_submission(text="")

        with self.assertRaises(ValidationError):
            submission.full_clean()

    def test_duplicate_assignment_student_blocked(self):
        self.make_submission()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.make_submission()

    def test_two_students_can_submit_same_assignment(self):
        self.make_submission(student=self.student)
        self.make_submission(student=self.student2)

        self.assertEqual(
            Submission.objects.filter(
                assignment=self.assignment
            ).count(),
            2,
        )

    def test_submission_deleted_when_assignment_deleted(self):
        self.make_submission()

        assignment_id = self.assignment.pk

        # Model-level CASCADE behavior.
        self.assignment.delete()

        self.assertFalse(
            Submission.objects.filter(
                assignment_id=assignment_id
            ).exists()
        )

    def test_submission_student_relationship(self):
        submission = self.make_submission()

        self.assertEqual(
            submission.student,
            self.student,
        )

    def test_submission_assignment_relationship(self):
        submission = self.make_submission()

        self.assertEqual(
            submission.assignment,
            self.assignment,
        )


# ============================================================
# 13. CSRF SECURITY TESTS
# ============================================================

class CSRFSecurityTests(AssignmentTestBase):

    def setUp(self):
        super().setUp()

        self.secure_client = Client(
            enforce_csrf_checks=True
        )

    def test_create_without_csrf_rejected(self):
        self.secure_client.force_login(self.teacher)

        response = self.secure_client.post(
            reverse("assignments:create"),
            self.assignment_data(),
        )

        self.assertEqual(response.status_code, 403)

    def test_edit_without_csrf_rejected(self):
        self.secure_client.force_login(self.teacher)

        response = self.secure_client.post(
            reverse(
                "assignments:edit",
                args=[self.assignment.pk],
            ),
            self.assignment_data(),
        )

        self.assertEqual(response.status_code, 403)

    def test_delete_without_csrf_rejected(self):
        self.secure_client.force_login(self.teacher)

        response = self.secure_client.post(
            reverse(
                "assignments:delete",
                args=[self.assignment.pk],
            ),
        )

        self.assertEqual(response.status_code, 403)

    def test_submission_without_csrf_rejected(self):
        self.secure_client.force_login(self.student)

        response = self.secure_client.post(
            self.submit_url(),
            {"text_content": "Answer"},
        )

        self.assertEqual(response.status_code, 403)

    def test_grading_without_csrf_rejected(self):
        submission = self.make_submission()

        self.secure_client.force_login(self.teacher)

        response = self.secure_client.post(
            self.review_url(submission),
            {
                "marks": "90",
                "feedback": "Good",
            },
        )

        self.assertEqual(response.status_code, 403)


# ============================================================
# 14. HTTP METHOD AND REQUEST SECURITY
# ============================================================

class RequestSecurityTests(AssignmentTestBase):

    def test_get_create_does_not_create_record(self):
        self.login_as(self.teacher)

        before = Assignment.objects.count()

        response = self.client.get(
            reverse("assignments:create")
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            Assignment.objects.count(),
            before,
        )

    def test_get_submit_does_not_finalize_submission(self):
        self.login_as(self.student)

        self.client.get(self.submit_url())

        self.assertFalse(
            Submission.objects.filter(
                assignment=self.assignment,
                student=self.student,
                status=Submission.Status.SUBMITTED,
            ).exists()
        )

    def test_get_review_does_not_grade(self):
        submission = self.make_submission()

        self.login_as(self.teacher)

        response = self.client.get(
            self.review_url(submission)
        )

        self.assertEqual(response.status_code, 200)

        submission.refresh_from_db()

        self.assertIsNone(submission.marks)

    def test_sql_injection_style_answer_stored_as_text(self):
        self.login_as(self.student)

        payload = "'; DROP TABLE assignments_submission; --"

        response = self.client.post(
            self.submit_url(),
            {"text_content": payload},
        )

        self.assertEqual(response.status_code, 302)

        submission = Submission.objects.get(
            assignment=self.assignment,
            student=self.student,
        )

        self.assertEqual(
            submission.text_content,
            payload,
        )

    def test_xss_answer_is_html_escaped(self):
        submission = self.make_submission(
            text="<script>alert('xss')</script>"
        )

        self.login_as(self.teacher)

        response = self.client.get(
            self.review_url(submission)
        )

        self.assertEqual(response.status_code, 200)

        self.assertNotContains(
            response,
            "<script>alert('xss')</script>",
        )

    def test_invalid_assignment_id_returns_404(self):
        self.login_as(self.teacher)

        response = self.client.get(
            reverse(
                "assignments:detail",
                args=[999999],
            )
        )

        self.assertEqual(response.status_code, 404)


# ============================================================
# 15. END-TO-END USER WORKFLOW TESTS
# ============================================================

class EndToEndWorkflowTests(AssignmentTestBase):

    def test_teacher_create_student_submit_teacher_grade(self):

        # Step 1: Teacher creates an assignment.
        self.login_as(self.teacher)

        create_response = self.client.post(
            reverse("assignments:create"),
            self.assignment_data(
                title="Complete E2E Assignment"
            ),
        )

        self.assertEqual(
            create_response.status_code,
            302,
        )

        assignment = Assignment.objects.get(
            title="Complete E2E Assignment"
        )

        # Step 2: Student logs in and views assignment.
        self.client.logout()
        self.login_as(self.student)

        detail_response = self.client.get(
            reverse(
                "assignments:detail",
                args=[assignment.pk],
            )
        )

        self.assertEqual(
            detail_response.status_code,
            200,
        )

        # Step 3: Student submits their answer.
        submit_response = self.client.post(
            reverse(
                "assignments:submit",
                args=[assignment.pk],
            ),
            {
                "text_content": (
                    "Software engineering uses "
                    "structured development processes."
                ),
            },
        )

        self.assertEqual(
            submit_response.status_code,
            302,
        )

        submission = Submission.objects.get(
            assignment=assignment,
            student=self.student,
        )

        self.assertEqual(
            submission.status,
            Submission.Status.SUBMITTED,
        )

        # Step 4: Student cannot submit twice.
        duplicate_response = self.client.post(
            reverse(
                "assignments:submit",
                args=[assignment.pk],
            ),
            {
                "text_content": "Second attempt",
            },
        )

        self.assertEqual(
            duplicate_response.status_code,
            403,
        )

        # Step 5: Teacher reviews submission.
        self.client.logout()
        self.login_as(self.teacher)

        review_response = self.client.get(
            reverse(
                "assignments:submission_review",
                args=[submission.pk],
            )
        )

        self.assertEqual(
            review_response.status_code,
            200,
        )

        # Step 6: Teacher assigns marks.
        grade_response = self.client.post(
            reverse(
                "assignments:submission_review",
                args=[submission.pk],
            ),
            {
                "marks": "88.50",
                "feedback": (
                    "Good understanding of the topic."
                ),
            },
        )

        self.assertEqual(
            grade_response.status_code,
            302,
        )

        submission.refresh_from_db()

        self.assertEqual(
            submission.status,
            Submission.Status.GRADED,
        )

        self.assertEqual(
            submission.marks,
            Decimal("88.50"),
        )

        # Step 7: Student cannot modify graded answer.
        self.client.logout()
        self.login_as(self.student)

        update_response = self.client.post(
            reverse(
                "assignments:submit",
                args=[assignment.pk],
            ),
            {
                "text_content": "Modified after grading",
            },
        )

        self.assertEqual(
            update_response.status_code,
            403,
        )

        submission.refresh_from_db()

        self.assertIn(
            "structured development",
            submission.text_content,
        )

    def test_two_students_submit_independently(self):

        self.login_as(self.student)

        response1 = self.client.post(
            self.submit_url(),
            {
                "text_content": "Student one answer",
            },
        )

        self.assertEqual(response1.status_code, 302)

        self.client.logout()
        self.login_as(self.student2)

        response2 = self.client.post(
            self.submit_url(),
            {
                "text_content": "Student two answer",
            },
        )

        self.assertEqual(response2.status_code, 302)

        self.assertEqual(
            Submission.objects.filter(
                assignment=self.assignment
            ).count(),
            2,
        )

    def test_assignment_deadline_blocks_new_submission(self):

        self.login_as(self.student)

        self.assignment.deadline = past_date()
        self.assignment.save()

        response = self.client.post(
            self.submit_url(),
            {
                "text_content": "Late submission",
            },
        )

        self.assertEqual(response.status_code, 403)

        self.assertFalse(
            Submission.objects.filter(
                assignment=self.assignment,
                student=self.student,
            ).exists()
        )

    def test_teacher_cannot_grade_another_teachers_student(self):

        submission = self.make_submission(
            assignment=self.other_assignment,
            student=self.student2,
        )

        self.login_as(self.teacher)

        response = self.client.post(
            self.review_url(submission),
            {
                "marks": "50",
                "feedback": "Unauthorized",
            },
        )

        self.assertEqual(response.status_code, 403)

        submission.refresh_from_db()

        self.assertIsNone(submission.marks)

    def test_student_cannot_read_another_students_answer(self):

        submission = self.make_submission(
            student=self.student2,
            text="PRIVATE STUDENT ANSWER",
        )

        self.login_as(self.student)

        response = self.client.get(
            self.detail_url()
        )

        self.assertEqual(response.status_code, 200)

        self.assertNotContains(
            response,
            "PRIVATE STUDENT ANSWER",
        )

        self.assertNotContains(
            response,
            self.student2.username,
        )

# ============================================================
# 16. COURSE OFFERING / ENROLLMENT SECURITY REGRESSION
# ============================================================

class CourseAccessRegressionTests(AssignmentTestBase):

    def test_unenrolled_student_cannot_view_assignment(self):
        stranger = create_user(
            "student_stranger", UserProfile.Role.STUDENT
        )
        self.login_as(stranger)
        response = self.client.get(self.detail_url())
        self.assertEqual(response.status_code, 403)

    def test_unenrolled_student_cannot_submit(self):
        stranger = create_user(
            "student_stranger", UserProfile.Role.STUDENT
        )
        self.login_as(stranger)
        response = self.client.post(
            self.submit_url(), {"text_content": "Not enrolled"}
        )
        self.assertEqual(response.status_code, 403)

    def test_dropped_student_cannot_access_published_assignment(self):
        self.enrollment.status = CourseEnrollment.Status.DROPPED
        self.enrollment.save(update_fields=["status"])
        self.login_as(self.student)
        self.assertEqual(self.client.get(self.detail_url()).status_code, 403)

    def test_cross_offering_student_cannot_view(self):
        # A student enrolled in CS101 Section A cannot automatically
        # see CS102 Section B's published assignment.
        self.login_as(self.student)
        response = self.client.get(self.detail_url(self.other_assignment))
        self.assertEqual(response.status_code, 403)

    def test_forged_offering_rejected_on_assignment_creation(self):
        self.login_as(self.teacher)

        response = self.client.post(
            reverse("assignments:create"),
            self.assignment_data(
                course_offering=self.other_offering.pk,
            ),
        )

        self.assertEqual(response.status_code, 200)

        self.assertIn(
            "course_offering",
            response.context["form"].errors,
        )
    def test_published_assignment_requires_offering(self):
        self.login_as(self.teacher)
        response = self.client.post(
            reverse("assignments:create"),
            self.assignment_data(course_offering=""),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("course_offering", response.context["form"].errors)
class AssignmentRosterTests(AssignmentTestBase):

    def roster_url(self, assignment=None):
        return reverse(
            "assignments:roster",
            args=[
                (assignment or self.assignment).pk
            ],
        )

    def test_teacher_can_view_own_roster(self):
        self.login_as(self.teacher)

        response = self.client.get(
            self.roster_url()
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.context["total_students"],
            2,
        )

    def test_teacher_cannot_view_other_roster(self):
        self.login_as(self.teacher2)

        response = self.client.get(
            self.roster_url()
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_student_cannot_view_roster(self):
        self.login_as(self.student)

        response = self.client.get(
            self.roster_url()
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_roster_counts_submitted_and_pending(self):
        self.make_submission(
            student=self.student,
        )

        self.login_as(self.teacher)

        response = self.client.get(
            self.roster_url()
        )

        self.assertEqual(
            response.context["total_students"],
            2,
        )

        self.assertEqual(
            response.context["submitted_count"],
            1,
        )

        self.assertEqual(
            response.context["pending_count"],
            1,
        )

    def test_roster_counts_graded_submissions(self):
        self.make_submission(
            student=self.student,
            status=Submission.Status.GRADED,
            marks=Decimal("85.00"),
        )

        self.login_as(self.teacher)

        response = self.client.get(
            self.roster_url()
        )

        self.assertEqual(
            response.context["graded_count"],
            1,
        )

        self.assertEqual(
            response.context["submitted_count"],
            1,
        )

    def test_teacher_assignment_list_has_class_info(self):
        self.login_as(self.teacher)

        response = self.client.get(
            reverse("assignments:list")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertContains(
            response,
            self.course.code,
        )

        self.assertContains(
            response,
            self.section.code,
        )
    def test_expired_empty_attempt_shows_not_submitted(self):
        from timed_writing.models import (
            TimedWritingAttempt,
            TimedWritingConfig,
        )

        config = TimedWritingConfig.objects.create(
            assignment=self.assignment,
            duration_minutes=30,
            is_enabled=True,
        )

        submission = self.make_submission(
            status=Submission.Status.DRAFT,
            text="",
        )

        TimedWritingAttempt.objects.create(
            config=config,
            student=self.student,
            submission=submission,
            started_at=timezone.now() - timedelta(hours=1),
            expires_at=timezone.now() - timedelta(minutes=30),
            status=TimedWritingAttempt.Status.EXPIRED,
        )

        self.login_as(self.teacher)

        response = self.client.get(
            self.roster_url()
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.context["submitted_count"],
            0,
        )

        self.assertEqual(
            response.context["pending_count"],
            2,
        )

        self.assertContains(
            response,
            "Expired",
        )