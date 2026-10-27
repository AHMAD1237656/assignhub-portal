
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from assignments.models import Assignment, Submission
from departments.models import Department, Program
from semesters.models import Section, Semester

from .models import (
    Course,
    CourseEnrollment,
    CourseOffering,
)


User = get_user_model()


def set_role(user, role):
    UserProfile.objects.update_or_create(
        user=user,
        defaults={"role": role},
    )


class CoursesTestBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="courses_admin",
            email="courses_admin@example.com",
            password="TestPassword123!",
        )

        cls.teacher = User.objects.create_user(
            username="courses_teacher",
            password="TestPassword123!",
        )
        set_role(
            cls.teacher,
            UserProfile.Role.TEACHER,
        )

        cls.other_teacher = User.objects.create_user(
            username="courses_other_teacher",
            password="TestPassword123!",
        )
        set_role(
            cls.other_teacher,
            UserProfile.Role.TEACHER,
        )

        cls.student = User.objects.create_user(
            username="courses_student",
            password="TestPassword123!",
        )
        set_role(
            cls.student,
            UserProfile.Role.STUDENT,
        )

        cls.other_student = User.objects.create_user(
            username="courses_other_student",
            password="TestPassword123!",
        )
        set_role(
            cls.other_student,
            UserProfile.Role.STUDENT,
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
        )

        cls.section_b = Section.objects.create(
            semester=cls.semester1,
            code="B",
        )

        cls.section_second = Section.objects.create(
            semester=cls.semester2,
            code="A",
        )

        cls.course = Course.objects.create(
            program=cls.program,
            semester=cls.semester1,
            code="CS101",
            title="Programming Fundamentals",
            credit_hours=3,
        )

        cls.other_course = Course.objects.create(
            program=cls.program,
            semester=cls.semester2,
            code="CS201",
            title="Data Structures",
            credit_hours=3,
        )

        cls.offering = CourseOffering.objects.create(
            course=cls.course,
            section=cls.section_a,
            teacher=cls.teacher,
            academic_year="2026-2027",
            term=CourseOffering.Term.FALL,
        )

        cls.other_offering = CourseOffering.objects.create(
            course=cls.course,
            section=cls.section_b,
            teacher=cls.other_teacher,
            academic_year="2026-2027",
            term=CourseOffering.Term.FALL,
        )

        cls.enrollment = CourseEnrollment.objects.create(
            offering=cls.offering,
            student=cls.student,
        )

    def login(self, user=None):
        self.client.force_login(user or self.admin)

    def url(self, route, pk=None):
        kwargs = {"pk": pk} if pk is not None else {}

        return reverse(
            f"courses:{route}",
            kwargs=kwargs,
        )

    def course_data(self, **changes):
        data = {
            "program": self.program.pk,
            "semester": self.semester1.pk,
            "code": "CS102",
            "title": "Computer Applications",
            "credit_hours": 3,
            "description": "Course description",
            "is_active": "on",
        }

        data.update(changes)
        return data

    def offering_data(self, **changes):
        data = {
            "course": self.other_course.pk,
            "section": self.section_second.pk,
            "teacher": self.teacher.pk,
            "academic_year": "2026-2027",
            "term": CourseOffering.Term.FALL,
            "is_active": "on",
        }

        data.update(changes)
        return data

    def future_deadline(self):
        return (
            timezone.now() + timedelta(days=5)
        ).strftime("%Y-%m-%dT%H:%M")

    def assignment_data(self, **changes):
        data = {
            "course_offering": self.offering.pk,
            "title": "Programming Assignment",
            "instructions": "Solve the problems.",
            "deadline": self.future_deadline(),
            "total_marks": 100,
            "rubric": "Correctness",
            "status": "PUBLISHED",
        }

        data.update(changes)
        return data


class CoursePermissionTests(CoursesTestBase):

    def test_anonymous_redirected(self):
        response = self.client.get(
            self.url("course_list")
        )
        self.assertEqual(response.status_code, 302)

    def test_student_denied_course_management(self):
        self.login(self.student)

        response = self.client.get(
            self.url("course_list")
        )
        self.assertEqual(response.status_code, 403)

    def test_teacher_denied_course_create(self):
        self.login(self.teacher)

        response = self.client.post(
            self.url("course_create"),
            self.course_data(),
        )
        self.assertEqual(response.status_code, 403)

    def test_teacher_sees_own_offering(self):
        self.login(self.teacher)

        response = self.client.get(
            self.url("offering_list")
        )

        self.assertEqual(response.status_code, 200)

        records = list(response.context["page_obj"])

        self.assertIn(self.offering, records)
        self.assertNotIn(self.other_offering, records)

    def test_teacher_cannot_open_other_offering(self):
        self.login(self.teacher)

        response = self.client.get(
            self.url(
                "offering_detail",
                self.other_offering.pk,
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_teacher_cannot_edit_offering(self):
        self.login(self.teacher)

        response = self.client.get(
            self.url(
                "offering_edit",
                self.offering.pk,
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_teacher_cannot_enroll_student(self):
        self.login(self.teacher)

        response = self.client.get(
            self.url("enrollment_create")
        )

        self.assertEqual(response.status_code, 403)

    def test_student_denied_dropdown_api(self):
        self.login(self.student)

        response = self.client.get(
            self.url("sections_for_course_api"),
            {"course": self.course.pk},
        )

        self.assertEqual(response.status_code, 403)


class CourseCRUDTests(CoursesTestBase):

    def setUp(self):
        self.login()

    def test_course_list(self):
        response = self.client.get(
            self.url("course_list")
        )
        self.assertEqual(response.status_code, 200)

    def test_course_detail(self):
        response = self.client.get(
            self.url(
                "course_detail",
                self.course.pk,
            )
        )
        self.assertEqual(response.status_code, 200)

    def test_create_course(self):
        response = self.client.post(
            self.url("course_create"),
            self.course_data(),
        )

        self.assertEqual(response.status_code, 302)

        self.assertTrue(
            Course.objects.filter(
                program=self.program,
                code="CS102",
            ).exists()
        )

    def test_code_normalized_uppercase(self):
        response = self.client.post(
            self.url("course_create"),
            self.course_data(code="cs102"),
        )

        self.assertEqual(response.status_code, 302)

        self.assertTrue(
            Course.objects.filter(
                code="CS102",
            ).exists()
        )

    def test_duplicate_course_code_rejected(self):
        response = self.client.post(
            self.url("course_create"),
            self.course_data(code="cs101"),
        )

        self.assertEqual(response.status_code, 200)

        self.assertFalse(
            Course.objects.filter(
                code="CS102"
            ).exists()
        )

    def test_course_semester_must_match_program(self):
        other_department = Department.objects.create(
            code="IT",
            name="Information Technology",
        )

        other_program = Program.objects.create(
            department=other_department,
            code="BSIT",
            name="BS Information Technology",
            duration_semesters=8,
        )

        other_semester = Semester.objects.create(
            program=other_program,
            number=1,
        )

        response = self.client.post(
            self.url("course_create"),
            self.course_data(
                semester=other_semester.pk
            ),
        )

        self.assertEqual(response.status_code, 200)

    def test_credits_zero_rejected(self):
        response = self.client.post(
            self.url("course_create"),
            self.course_data(credit_hours=0),
        )

        self.assertEqual(response.status_code, 200)

        self.assertIn(
            "credit_hours",
            response.context["form"].errors,
        )

    def test_edit_course_title(self):
        response = self.client.post(
            self.url("course_edit", self.course.pk),
            self.course_data(
                code="CS101",
                title="Updated Fundamentals",
            ),
        )

        self.assertEqual(response.status_code, 302)

        self.course.refresh_from_db()

        self.assertEqual(
            self.course.title,
            "Updated Fundamentals",
        )

    def test_archive_course_with_active_offering_blocked(self):
        self.client.post(
            self.url(
                "course_toggle",
                self.course.pk,
            ),
            {"action": "archive"},
        )

        self.course.refresh_from_db()
        self.assertTrue(self.course.is_active)

    def test_archive_empty_course(self):
        self.client.post(
            self.url(
                "course_toggle",
                self.other_course.pk,
            ),
            {"action": "archive"},
        )

        self.other_course.refresh_from_db()
        self.assertFalse(self.other_course.is_active)

    def test_delete_course_with_offerings_blocked(self):
        response = self.client.post(
            self.url(
                "course_delete",
                self.course.pk,
            )
        )

        self.assertEqual(response.status_code, 302)

        self.assertTrue(
            Course.objects.filter(
                pk=self.course.pk
            ).exists()
        )

    def test_delete_course_without_offerings(self):
        pk = self.other_course.pk

        response = self.client.post(
            self.url("course_delete", pk)
        )

        self.assertEqual(response.status_code, 302)

        self.assertFalse(
            Course.objects.filter(pk=pk).exists()
        )


class OfferingCRUDTests(CoursesTestBase):

    def setUp(self):
        self.login()

    def test_create_offering(self):
        response = self.client.post(
            self.url("offering_create"),
            self.offering_data(),
        )

        self.assertEqual(response.status_code, 302)

        self.assertTrue(
            CourseOffering.objects.filter(
                course=self.other_course,
                section=self.section_second,
            ).exists()
        )

    def test_duplicate_offering_rejected(self):
        response = self.client.post(
            self.url("offering_create"),
            self.offering_data(
                course=self.course.pk,
                section=self.section_a.pk,
            ),
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            CourseOffering.objects.filter(
                course=self.course,
                section=self.section_a,
                academic_year="2026-2027",
                term="FALL",
            ).count(),
            1,
        )

    def test_cross_semester_section_rejected(self):
        response = self.client.post(
            self.url("offering_create"),
            self.offering_data(
                course=self.course.pk,
                section=self.section_second.pk,
            ),
        )

        self.assertEqual(response.status_code, 200)

    def test_non_teacher_assignment_rejected(self):
        response = self.client.post(
            self.url("offering_create"),
            self.offering_data(
                teacher=self.student.pk,
            ),
        )

        self.assertEqual(response.status_code, 200)

    def test_invalid_academic_year_rejected(self):
        response = self.client.post(
            self.url("offering_create"),
            self.offering_data(
                academic_year="2026-2029",
            ),
        )

        self.assertEqual(response.status_code, 200)

        self.assertIn(
            "academic_year",
            response.context["form"].errors,
        )

    def test_offering_api_filters_sections(self):
        response = self.client.get(
            self.url("sections_for_course_api"),
            {"course": self.course.pk},
        )

        self.assertEqual(response.status_code, 200)

        ids = {
            item["id"]
            for item in response.json()["results"]
        }

        self.assertEqual(
            ids,
            {
                self.section_a.pk,
                self.section_b.pk,
            },
        )

        self.assertNotIn(
            self.section_second.pk,
            ids,
        )

    def test_offering_edit_teacher(self):
        response = self.client.post(
            self.url(
                "offering_edit",
                self.other_offering.pk,
            ),
            self.offering_data(
                course=self.course.pk,
                section=self.section_b.pk,
                teacher=self.teacher.pk,
            ),
        )

        self.assertEqual(response.status_code, 302)

        self.other_offering.refresh_from_db()

        self.assertEqual(
            self.other_offering.teacher_id,
            self.teacher.pk,
        )

    def test_offering_cannot_change_after_enrollment(self):
        response = self.client.post(
            self.url(
                "offering_edit",
                self.offering.pk,
            ),
            self.offering_data(
                course=self.course.pk,
                section=self.section_a.pk,
                teacher=self.other_teacher.pk,
            ),
        )

        self.assertEqual(response.status_code, 200)

        self.assertIn(
            "teacher",
            response.context["form"].errors,
        )

    def test_delete_offering_with_enrollment_blocked(self):
        response = self.client.post(
            self.url(
                "offering_delete",
                self.offering.pk,
            )
        )

        self.assertEqual(response.status_code, 302)

        self.assertTrue(
            CourseOffering.objects.filter(
                pk=self.offering.pk
            ).exists()
        )

    def test_invalid_status_action_rejected(self):
        response = self.client.post(
            self.url(
                "offering_toggle",
                self.offering.pk,
            ),
            {"action": "invalid"},
        )

        self.assertEqual(response.status_code, 302)

        self.offering.refresh_from_db()
        self.assertTrue(self.offering.is_active)


class EnrollmentTests(CoursesTestBase):

    def setUp(self):
        self.login()

    def test_enrollment_list(self):
        response = self.client.get(
            self.url("enrollment_list")
        )
        self.assertEqual(response.status_code, 200)

    def test_enroll_student(self):
        response = self.client.post(
            self.url("enrollment_create"),
            {
                "offering": self.offering.pk,
                "student": self.other_student.pk,
                "status": "ACTIVE",
            },
        )

        self.assertEqual(response.status_code, 302)

        self.assertTrue(
            CourseEnrollment.objects.filter(
                offering=self.offering,
                student=self.other_student,
                status="ACTIVE",
            ).exists()
        )

    def test_duplicate_enrollment_rejected(self):
        response = self.client.post(
            self.url("enrollment_create"),
            {
                "offering": self.offering.pk,
                "student": self.student.pk,
                "status": "ACTIVE",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            CourseEnrollment.objects.filter(
                offering=self.offering,
                student=self.student,
            ).count(),
            1,
        )

    def test_drop_enrollment(self):
        response = self.client.post(
            self.url(
                "enrollment_delete",
                self.enrollment.pk,
            )
        )

        self.assertEqual(response.status_code, 302)

        self.enrollment.refresh_from_db()

        self.assertEqual(
            self.enrollment.status,
            CourseEnrollment.Status.DROPPED,
        )

    def test_restore_dropped_enrollment(self):
        self.enrollment.status = (
            CourseEnrollment.Status.DROPPED
        )
        self.enrollment.save()

        response = self.client.post(
            self.url(
                "enrollment_edit",
                self.enrollment.pk,
            ),
            {
                "status": "ACTIVE",
            },
        )

        self.assertEqual(response.status_code, 302)

        self.enrollment.refresh_from_db()

        self.assertEqual(
            self.enrollment.status,
            CourseEnrollment.Status.ACTIVE,
        )

    def test_cannot_enroll_teacher_as_student(self):
        response = self.client.post(
            self.url("enrollment_create"),
            {
                "offering": self.offering.pk,
                "student": self.teacher.pk,
                "status": "ACTIVE",
            },
        )

        self.assertEqual(response.status_code, 200)


class CourseSearchTests(CoursesTestBase):

    def setUp(self):
        self.login()

    def test_search_course_name(self):
        response = self.client.get(
            self.url("course_list"),
            {"q": "Fundamentals"},
        )

        self.assertEqual(
            list(response.context["page_obj"]),
            [self.course],
        )

    def test_filter_course_by_semester(self):
        response = self.client.get(
            self.url("course_list"),
            {
                "program": self.program.pk,
                "semester": self.semester2.pk,
            },
        )

        self.assertEqual(
            list(response.context["page_obj"]),
            [self.other_course],
        )

    def test_ajax_course_returns_partial(self):
        response = self.client.get(
            self.url("course_list"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertTemplateUsed(
            response,
            "courses/partials/course_results.html",
        )

    def test_ajax_offering_returns_partial(self):
        response = self.client.get(
            self.url("offering_list"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertTemplateUsed(
            response,
            "courses/partials/offering_results.html",
        )

    def test_ajax_enrollment_returns_partial(self):
        response = self.client.get(
            self.url("enrollment_list"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertTemplateUsed(
            response,
            "courses/partials/enrollment_results.html",
        )

    def test_invalid_filter_safe(self):
        response = self.client.get(
            self.url("course_list"),
            {"program": "bad-id"},
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            len(response.context["page_obj"]),
            0,
        )

    def test_live_search_delay_attribute(self):
        response = self.client.get(
            self.url("course_list")
        )

        self.assertContains(
            response,
            'data-debounce="200"',
        )


class DatabaseIntegrityTests(CoursesTestBase):

    def test_course_unique_constraint(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Course.objects.create(
                    program=self.program,
                    semester=self.semester1,
                    code="cs101",
                    title="Duplicate",
                )

    def test_offering_unique_constraint(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CourseOffering.objects.create(
                    course=self.course,
                    section=self.section_a,
                    teacher=self.teacher,
                    academic_year="2026-2027",
                    term="FALL",
                )

    def test_enrollment_unique_constraint(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CourseEnrollment.objects.create(
                    offering=self.offering,
                    student=self.student,
                )

    def test_invalid_credit_hours_db_constraint(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Course.objects.create(
                    program=self.program,
                    semester=self.semester1,
                    code="CS999",
                    title="Invalid Credits",
                    credit_hours=0,
                )

    def test_invalid_course_hierarchy(self):
        record = Course(
            program=self.program,
            semester=self.semester2,
            code="CS202",
            title="Valid Different Semester",
        )

        record.full_clean()

        self.assertEqual(
            record.semester.number,
            2,
        )

    def test_invalid_offering_hierarchy(self):
        record = CourseOffering(
            course=self.course,
            section=self.section_second,
            teacher=self.teacher,
            academic_year="2026-2027",
            term="FALL",
        )

        with self.assertRaises(ValidationError):
            record.full_clean()


class AssignmentIntegrationTests(CoursesTestBase):

    def test_teacher_can_publish_in_own_offering(self):
        self.login(self.teacher)

        response = self.client.post(
            reverse("assignments:create"),
            self.assignment_data(),
        )

        self.assertEqual(response.status_code, 302)

        assignment = Assignment.objects.get(
            title="Programming Assignment"
        )

        self.assertEqual(
            assignment.course_offering_id,
            self.offering.pk,
        )

        self.assertEqual(
            assignment.created_by_id,
            self.teacher.pk,
        )

    def test_teacher_cannot_publish_other_teacher_offering(self):
        self.login(self.teacher)

        response = self.client.post(
            reverse("assignments:create"),
            self.assignment_data(
                course_offering=self.other_offering.pk
            ),
        )

        self.assertEqual(response.status_code, 200)

        self.assertFalse(
            Assignment.objects.filter(
                title="Programming Assignment"
            ).exists()
        )

    def test_published_without_offering_rejected(self):
        self.login(self.teacher)

        response = self.client.post(
            reverse("assignments:create"),
            self.assignment_data(
                course_offering=""
            ),
        )

        self.assertEqual(response.status_code, 200)

        self.assertIn(
            "course_offering",
            response.context["form"].errors,
        )

    def create_published_assignment(self):
        return Assignment.objects.create(
            created_by=self.teacher,
            course_offering=self.offering,
            title="Test Assignment",
            instructions="Complete the exercise.",
            total_marks=100,
            deadline=timezone.now()
            + timedelta(days=5),
            status=Assignment.Status.PUBLISHED,
        )

    def test_enrolled_student_can_view_assignment(self):
        assignment = self.create_published_assignment()

        self.login(self.student)

        response = self.client.get(
            reverse(
                "assignments:detail",
                args=[assignment.pk],
            )
        )

        self.assertEqual(response.status_code, 200)

    def test_non_enrolled_student_denied(self):
        assignment = self.create_published_assignment()

        self.login(self.other_student)

        response = self.client.get(
            reverse(
                "assignments:detail",
                args=[assignment.pk],
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_student_list_only_enrolled_courses(self):
        own_assignment = self.create_published_assignment()

        other_assignment = Assignment.objects.create(
            created_by=self.other_teacher,
            course_offering=self.other_offering,
            title="Other Section Assignment",
            instructions="Submit work.",
            total_marks=50,
            deadline=timezone.now()
            + timedelta(days=5),
            status=Assignment.Status.PUBLISHED,
        )

        self.login(self.student)

        response = self.client.get(
            reverse("assignments:list")
        )

        records = list(
            response.context["assignments"]
        )

        self.assertIn(own_assignment, records)
        self.assertNotIn(other_assignment, records)

    def test_enrolled_student_can_submit(self):
        assignment = self.create_published_assignment()

        self.login(self.student)

        response = self.client.post(
            reverse(
                "assignments:submit",
                args=[assignment.pk],
            ),
            {
                "text_content": "My final answer."
            },
        )

        self.assertEqual(response.status_code, 302)

        self.assertTrue(
            Submission.objects.filter(
                assignment=assignment,
                student=self.student,
                status=Submission.Status.SUBMITTED,
            ).exists()
        )

    def test_non_enrolled_student_cannot_submit(self):
        assignment = self.create_published_assignment()

        self.login(self.other_student)

        response = self.client.post(
            reverse(
                "assignments:submit",
                args=[assignment.pk],
            ),
            {
                "text_content": "Unauthorized answer."
            },
        )

        self.assertEqual(response.status_code, 403)

        self.assertFalse(
            Submission.objects.filter(
                assignment=assignment,
                student=self.other_student,
            ).exists()
        )

    def test_dropped_student_cannot_submit(self):
        assignment = self.create_published_assignment()

        self.enrollment.status = (
            CourseEnrollment.Status.DROPPED
        )
        self.enrollment.save()

        self.login(self.student)

        response = self.client.post(
            reverse(
                "assignments:submit",
                args=[assignment.pk],
            ),
            {
                "text_content": "Answer."
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_legacy_unlinked_assignment_hidden(self):
        legacy = Assignment.objects.create(
            created_by=self.teacher,
            title="Legacy Assignment",
            instructions="Old record.",
            deadline=timezone.now()
            + timedelta(days=5),
            status=Assignment.Status.PUBLISHED,
        )

        self.login(self.student)

        response = self.client.get(
            reverse(
                "assignments:detail",
                args=[legacy.pk],
            )
        )

        self.assertEqual(response.status_code, 403)


class SecurityTests(CoursesTestBase):

    def test_course_create_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)

        response = client.post(
            self.url("course_create"),
            self.course_data(),
        )

        self.assertEqual(response.status_code, 403)

    def test_toggle_requires_post(self):
        self.login()

        response = self.client.get(
            self.url(
                "course_toggle",
                self.course.pk,
            )
        )

        self.assertEqual(response.status_code, 405)

    def test_teacher_ajax_permissions(self):
        self.login(self.teacher)

        response = self.client.get(
            self.url("course_list"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 403)

    def test_student_cannot_see_enrollments(self):
        self.login(self.student)

        response = self.client.get(
            self.url("enrollment_list")
        )

        self.assertEqual(response.status_code, 403)
