
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from assignments.models import Assignment
from courses.models import CourseEnrollment
from semesters.models import Semester

from .tests import CoursesTestBase


class AcademicIntegrationHardeningTests(CoursesTestBase):

    def make_assignment(self, offering=None):
        offering = offering or self.offering

        return Assignment.objects.create(
            course_offering=offering,
            created_by=offering.teacher,
            title="Security Test Assignment",
            instructions="Complete the task.",
            deadline=timezone.now()
            + timedelta(days=7),
            total_marks=100,
            status=Assignment.Status.PUBLISHED,
        )

    def test_cannot_archive_offering_with_active_enrollments(self):
        self.login()

        response = self.client.post(
            self.url(
                "offering_toggle",
                self.offering.pk,
            ),
            {"action": "archive"},
        )

        self.assertEqual(response.status_code, 302)

        self.offering.refresh_from_db()
        self.assertTrue(self.offering.is_active)

    def test_cannot_archive_offering_with_published_assignment(self):
        self.login()

        self.make_assignment()

        self.enrollment.status = (
            CourseEnrollment.Status.DROPPED
        )
        self.enrollment.save()

        self.client.post(
            self.url(
                "offering_toggle",
                self.offering.pk,
            ),
            {"action": "archive"},
        )

        self.offering.refresh_from_db()
        self.assertTrue(self.offering.is_active)

    def test_teacher_can_close_own_assignment(self):
        assignment = self.make_assignment()

        self.login(self.teacher)

        response = self.client.post(
            reverse(
                "assignments:close",
                args=[assignment.pk],
            )
        )

        self.assertEqual(response.status_code, 302)

        assignment.refresh_from_db()

        self.assertEqual(
            assignment.status,
            Assignment.Status.CLOSED,
        )

    def test_other_teacher_cannot_close_assignment(self):
        assignment = self.make_assignment()

        self.login(self.other_teacher)

        response = self.client.post(
            reverse(
                "assignments:close",
                args=[assignment.pk],
            )
        )

        self.assertEqual(response.status_code, 403)

        assignment.refresh_from_db()

        self.assertEqual(
            assignment.status,
            Assignment.Status.PUBLISHED,
        )

    def test_close_assignment_requires_post(self):
        assignment = self.make_assignment()

        self.login(self.teacher)

        response = self.client.get(
            reverse(
                "assignments:close",
                args=[assignment.pk],
            )
        )

        self.assertEqual(response.status_code, 405)

    def test_close_assignment_requires_csrf(self):
        assignment = self.make_assignment()

        client = Client(enforce_csrf_checks=True)
        client.force_login(self.teacher)

        response = client.post(
            reverse(
                "assignments:close",
                args=[assignment.pk],
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_archive_after_close_and_drop(self):
        assignment = self.make_assignment()

        self.login(self.teacher)

        self.client.post(
            reverse(
                "assignments:close",
                args=[assignment.pk],
            )
        )

        self.login(self.admin)

        self.client.post(
            self.url(
                "enrollment_delete",
                self.enrollment.pk,
            )
        )

        response = self.client.post(
            self.url(
                "offering_toggle",
                self.offering.pk,
            ),
            {"action": "archive"},
        )

        self.assertEqual(response.status_code, 302)

        self.offering.refresh_from_db()
        self.assertFalse(self.offering.is_active)

    def test_duplicate_active_section_enrollment_rejected(self):
        second = CourseEnrollment(
            student=self.student,
            offering=self.other_offering,
            status=CourseEnrollment.Status.ACTIVE,
        )

        with self.assertRaises(ValidationError):
            second.full_clean()

    def test_archiving_section_with_active_offering_blocked(self):
        self.section_a.is_active = False

        with self.assertRaises(ValidationError):
            self.section_a.full_clean()

    def test_archiving_semester_with_active_course_blocked(self):
        semester = Semester.objects.create(
            program=self.program,
            number=3,
        )

        from courses.models import Course

        Course.objects.create(
            program=self.program,
            semester=semester,
            code="CS301",
            title="Software Engineering",
        )

        semester.is_active = False

        with self.assertRaises(ValidationError):
            semester.full_clean()

    def test_dropped_student_not_in_published_assignment_list(self):
        assignment = self.make_assignment()

        self.enrollment.status = (
            CourseEnrollment.Status.DROPPED
        )
        self.enrollment.save()

        self.login(self.student)

        response = self.client.get(
            reverse("assignments:list")
        )

        self.assertNotIn(
            assignment,
            list(response.context["assignments"]),
        )
