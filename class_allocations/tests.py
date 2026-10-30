from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserProfile
from courses.models import (
    Course,
    CourseEnrollment,
    CourseOffering,
)
from departments.models import Department, Program
from semesters.models import Semester, Section

from .models import StudentClassAllocation
from .services import allocate_students


User = get_user_model()


def create_user(username, role=None, is_staff=False):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="StrongTestPassword123!",
        is_staff=is_staff,
    )

    if role is not None:
        UserProfile.objects.create(
            user=user,
            role=role,
        )

    return user


class ClassAllocationTests(TestCase):

    @classmethod
    def setUpTestData(cls):

        cls.admin = User.objects.create_superuser(
            username="allocation_admin",
            email="allocation_admin@example.com",
            password="StrongAdminPassword123!",
        )

        cls.teacher = create_user(
            "allocation_teacher",
            UserProfile.Role.TEACHER,
        )

        cls.other_teacher = create_user(
            "allocation_other_teacher",
            UserProfile.Role.TEACHER,
        )

        cls.student1 = create_user(
            "allocation_student1",
            UserProfile.Role.STUDENT,
        )

        cls.student2 = create_user(
            "allocation_student2",
            UserProfile.Role.STUDENT,
        )

        cls.student3 = create_user(
            "allocation_student3",
            UserProfile.Role.STUDENT,
        )

        cls.department = Department.objects.create(
            code="ALC-DEP",
            name="Allocation Test Department",
        )

        cls.program = Program.objects.create(
            department=cls.department,
            code="ALC-BSSE",
            name="Allocation Test Software Engineering",
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
            semester=cls.semester1,
            code="B",
            capacity=40,
        )

        cls.section_next = Section.objects.create(
            semester=cls.semester2,
            code="C",
            capacity=40,
        )

        cls.course1 = Course.objects.create(
            program=cls.program,
            semester=cls.semester1,
            code="ALC101",
            title="Programming Fundamentals",
            credit_hours=3,
        )

        cls.course2 = Course.objects.create(
            program=cls.program,
            semester=cls.semester1,
            code="ALC102",
            title="Database Fundamentals",
            credit_hours=3,
        )

        cls.next_course = Course.objects.create(
            program=cls.program,
            semester=cls.semester2,
            code="ALC201",
            title="Advanced Programming",
            credit_hours=3,
        )

        cls.offering_a1 = CourseOffering.objects.create(
            course=cls.course1,
            section=cls.section_a,
            teacher=cls.teacher,
            academic_year="2026-2027",
            term=CourseOffering.Term.FALL,
        )

        cls.offering_a2 = CourseOffering.objects.create(
            course=cls.course2,
            section=cls.section_a,
            teacher=cls.teacher,
            academic_year="2026-2027",
            term=CourseOffering.Term.FALL,
        )

        cls.offering_b = CourseOffering.objects.create(
            course=cls.course1,
            section=cls.section_b,
            teacher=cls.other_teacher,
            academic_year="2026-2027",
            term=CourseOffering.Term.FALL,
        )

        cls.offering_next = CourseOffering.objects.create(
            course=cls.next_course,
            section=cls.section_next,
            teacher=cls.teacher,
            academic_year="2027-2028",
            term=CourseOffering.Term.FALL,
        )

    def allocation_data(self, **overrides):
        data = {
            "section": self.section_a.pk,
            "academic_year": "2026-2027",
            "term": CourseOffering.Term.FALL,
            "usernames": self.student1.username,
            "reason": "Test allocation",
        }

        data.update(overrides)
        return data

    def allocate(self, students=None, **overrides):
        return allocate_students(
            students=students or [self.student1],
            section=overrides.get(
                "section",
                self.section_a,
            ),
            academic_year=overrides.get(
                "academic_year",
                "2026-2027",
            ),
            term=overrides.get(
                "term",
                CourseOffering.Term.FALL,
            ),
            assigned_by=self.admin,
            allow_transfer=overrides.get(
                "allow_transfer",
                False,
            ),
            reason="Automated test",
        )

    # -----------------------------------------
    # ACCESS CONTROL
    # -----------------------------------------

    def test_admin_can_open_dashboard(self):
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("class_allocations:dashboard")
        )

        self.assertEqual(response.status_code, 200)

    def test_teacher_cannot_open_admin_dashboard(self):
        self.client.force_login(self.teacher)

        response = self.client.get(
            reverse("class_allocations:dashboard")
        )

        self.assertEqual(response.status_code, 403)

    def test_student_cannot_allocate(self):
        self.client.force_login(self.student1)

        response = self.client.post(
            reverse("class_allocations:allocate"),
            self.allocation_data(),
        )

        self.assertEqual(response.status_code, 403)

        self.assertEqual(
            StudentClassAllocation.objects.count(),
            0,
        )

    def test_teacher_cannot_allocate(self):
        self.client.force_login(self.teacher)

        response = self.client.post(
            reverse("class_allocations:allocate"),
            self.allocation_data(),
        )

        self.assertEqual(response.status_code, 403)

    # -----------------------------------------
    # INDIVIDUAL AND BULK ALLOCATION
    # -----------------------------------------

    def test_individual_allocation_enrolls_all_courses(self):
        result = self.allocate()

        self.assertEqual(result.created, 1)
        self.assertEqual(result.enrollments_created, 2)

        self.assertTrue(
            StudentClassAllocation.objects.filter(
                student=self.student1,
                section=self.section_a,
                status="ACTIVE",
            ).exists()
        )

        self.assertEqual(
            CourseEnrollment.objects.filter(
                student=self.student1,
                status=CourseEnrollment.Status.ACTIVE,
                offering__section=self.section_a,
            ).count(),
            2,
        )

    def test_bulk_allocation(self):
        result = self.allocate(
            students=[
                self.student1,
                self.student2,
                self.student3,
            ]
        )

        self.assertEqual(result.created, 3)

        self.assertEqual(
            CourseEnrollment.objects.filter(
                student__in=[
                    self.student1,
                    self.student2,
                    self.student3,
                ],
                status=CourseEnrollment.Status.ACTIVE,
                offering__section=self.section_a,
            ).count(),
            6,
        )

    def test_repeated_allocation_is_idempotent(self):
        self.allocate()
        result = self.allocate()

        self.assertEqual(result.created, 0)
        self.assertEqual(result.already_allocated, 1)

        self.assertEqual(
            StudentClassAllocation.objects.filter(
                student=self.student1,
                status="ACTIVE",
            ).count(),
            1,
        )

        self.assertEqual(
            CourseEnrollment.objects.filter(
                student=self.student1,
                status=CourseEnrollment.Status.ACTIVE,
            ).count(),
            2,
        )

    def test_admin_form_allocates_multiple_students(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("class_allocations:allocate"),
            self.allocation_data(
                usernames=(
                    "allocation_student1\n"
                    "allocation_student2"
                )
            ),
        )

        self.assertEqual(response.status_code, 302)

        self.assertEqual(
            StudentClassAllocation.objects.filter(
                status="ACTIVE"
            ).count(),
            2,
        )

    # -----------------------------------------
    # VALIDATION
    # -----------------------------------------

    def test_unknown_student_rejected(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("class_allocations:allocate"),
            self.allocation_data(
                usernames="missing_student"
            ),
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            StudentClassAllocation.objects.count(),
            0,
        )

    def test_teacher_username_rejected(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("class_allocations:allocate"),
            self.allocation_data(
                usernames=self.teacher.username
            ),
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            StudentClassAllocation.objects.count(),
            0,
        )

    def test_inactive_student_rejected(self):
        self.student1.is_active = False
        self.student1.save(
            update_fields=["is_active"]
        )

        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("class_allocations:allocate"),
            self.allocation_data(),
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            StudentClassAllocation.objects.count(),
            0,
        )

    def test_invalid_student_rejects_entire_bulk_form(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("class_allocations:allocate"),
            self.allocation_data(
                usernames=(
                    "allocation_student1\n"
                    "not_a_real_student"
                )
            ),
        )

        self.assertEqual(response.status_code, 200)

        self.assertFalse(
            StudentClassAllocation.objects.filter(
                student=self.student1
            ).exists()
        )

    def test_capacity_prevents_partial_allocation(self):
        self.section_a.capacity = 1
        self.section_a.save(
            update_fields=["capacity"]
        )

        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("class_allocations:allocate"),
            self.allocation_data(
                usernames=(
                    "allocation_student1\n"
                    "allocation_student2"
                )
            ),
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            StudentClassAllocation.objects.count(),
            0,
        )

        self.assertEqual(
            CourseEnrollment.objects.count(),
            0,
        )

    # -----------------------------------------
    # TRANSFER
    # -----------------------------------------

    def test_transfer_requires_explicit_permission(self):
        self.allocate()

        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("class_allocations:allocate"),
            self.allocation_data(
                section=self.section_b.pk
            ),
        )

        self.assertEqual(response.status_code, 200)

        self.assertTrue(
            StudentClassAllocation.objects.filter(
                student=self.student1,
                section=self.section_a,
                status="ACTIVE",
            ).exists()
        )

    def test_transfer_drops_old_enrollments(self):
        self.allocate()

        result = self.allocate(
            section=self.section_b,
            allow_transfer=True,
        )

        self.assertEqual(result.transferred, 1)

        self.assertTrue(
            StudentClassAllocation.objects.filter(
                student=self.student1,
                section=self.section_a,
                status="TRANSFERRED",
            ).exists()
        )

        self.assertTrue(
            StudentClassAllocation.objects.filter(
                student=self.student1,
                section=self.section_b,
                status="ACTIVE",
            ).exists()
        )

        self.assertEqual(
            CourseEnrollment.objects.filter(
                student=self.student1,
                offering__section=self.section_a,
                status=CourseEnrollment.Status.ACTIVE,
            ).count(),
            0,
        )

        self.assertEqual(
            CourseEnrollment.objects.filter(
                student=self.student1,
                offering=self.offering_b,
                status=CourseEnrollment.Status.ACTIVE,
            ).count(),
            1,
        )

    def test_unrelated_manual_enrollment_blocks_allocation(self):
        CourseEnrollment.objects.create(
            student=self.student1,
            offering=self.offering_b,
            status=CourseEnrollment.Status.ACTIVE,
        )

        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("class_allocations:allocate"),
            self.allocation_data(),
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            StudentClassAllocation.objects.count(),
            0,
        )

    # -----------------------------------------
    # SEMESTER PROMOTION
    # -----------------------------------------

    def test_new_period_preserves_old_allocation(self):
        self.allocate()

        result = self.allocate(
            section=self.section_next,
            academic_year="2027-2028",
        )

        self.assertEqual(result.created, 1)

        self.assertEqual(
            StudentClassAllocation.objects.filter(
                student=self.student1,
                status="ACTIVE",
            ).count(),
            2,
        )

        self.assertTrue(
            CourseEnrollment.objects.filter(
                student=self.student1,
                offering=self.offering_next,
                status=CourseEnrollment.Status.ACTIVE,
            ).exists()
        )

    # -----------------------------------------
    # SYNCHRONIZATION
    # -----------------------------------------

    def test_sync_restores_dropped_enrollment(self):
        self.allocate()

        enrollment = CourseEnrollment.objects.get(
            student=self.student1,
            offering=self.offering_a1,
        )

        enrollment.status = (
            CourseEnrollment.Status.DROPPED
        )
        enrollment.save(
            update_fields=["status"]
        )

        result = self.allocate()

        self.assertEqual(
            result.enrollments_restored,
            1,
        )

        enrollment.refresh_from_db()

        self.assertEqual(
            enrollment.status,
            CourseEnrollment.Status.ACTIVE,
        )

    def test_sync_does_not_enroll_archived_offering(self):
        self.offering_a2.is_active = False
        self.offering_a2.save(
            update_fields=["is_active"]
        )

        result = self.allocate()

        self.assertEqual(
            result.enrollments_created,
            1,
        )

        self.assertFalse(
            CourseEnrollment.objects.filter(
                student=self.student1,
                offering=self.offering_a2,
            ).exists()
        )

    def test_sync_endpoint_requires_post(self):
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("class_allocations:sync")
        )

        self.assertEqual(response.status_code, 405)

    # -----------------------------------------
    # TEACHER ROSTER SECURITY
    # -----------------------------------------

    def test_teacher_can_see_own_classes(self):
        self.client.force_login(self.teacher)

        response = self.client.get(
            reverse("class_allocations:my_classes")
        )

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            "ALC101",
        )

    def test_teacher_can_view_own_roster(self):
        self.allocate()

        self.client.force_login(self.teacher)

        response = self.client.get(
            reverse(
                "class_allocations:class_roster",
                args=[self.offering_a1.pk],
            )
        )

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            self.student1.username,
        )

    def test_other_teacher_cannot_view_roster(self):
        self.allocate()

        self.client.force_login(self.other_teacher)

        response = self.client.get(
            reverse(
                "class_allocations:class_roster",
                args=[self.offering_a1.pk],
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_student_cannot_view_teacher_roster(self):
        self.allocate()

        self.client.force_login(self.student1)

        response = self.client.get(
            reverse(
                "class_allocations:class_roster",
                args=[self.offering_a1.pk],
            )
        )

        self.assertEqual(response.status_code, 403)