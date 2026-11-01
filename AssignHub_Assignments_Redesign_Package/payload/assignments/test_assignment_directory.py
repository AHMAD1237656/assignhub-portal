"""Focused regression tests for the redesigned assignment listing.

Uses the existing project's real academic hierarchy fixtures.
"""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from courses.models import CourseOffering
from .models import Assignment, Submission
from .tests import AssignmentTestBase


class AssignmentDirectoryTests(AssignmentTestBase):
    def directory(self, **params):
        self.login_as(self.teacher)
        return self.client.get(reverse("assignments:list"), params)

    def make_for(self, offering, title, *, status=Assignment.Status.PUBLISHED):
        return Assignment.objects.create(
            course_offering=offering,
            created_by=self.teacher,
            title=title,
            instructions="Testing filters and pagination",
            deadline=timezone.now() + timedelta(days=8),
            total_marks=100,
            status=status,
        )

    def extra_teacher_offering(self, *, different_course=True):
        return CourseOffering.objects.create(
            course=self.other_course if different_course else self.course,
            section=self.other_section,
            teacher=self.teacher,
            academic_year="2026-2027",
            term=CourseOffering.Term.FALL,
        )

    def test_teacher_listing_preserves_existing_queryset_context(self):
        response = self.directory()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["can_create"])
        self.assertTrue(response.context["show_progress"])
        self.assertEqual(
            response.context["assignments"].filter(pk=self.assignment.pk).count(),
            1,
        )
        self.assertNotContains(response, "Database Assignment")
        self.assertContains(response, "Your Courses")
        self.assertContains(response, "Search &amp; Filters", html=False)

    def test_course_filter_prevents_other_course_results(self):
        second = self.extra_teacher_offering()
        other_assignment = self.make_for(second, "Relational Algebra Lab")
        response = self.directory(course=str(self.course.pk))
        self.assertEqual(response.status_code, 200)
        ids = list(response.context["assignments"].values_list("pk", flat=True))
        self.assertIn(self.assignment.pk, ids)
        self.assertNotIn(other_assignment.pk, ids)
        self.assertEqual(response.context["selected_course"], self.course.pk)

    def test_section_filter_separates_same_course_sections(self):
        section_b = self.extra_teacher_offering(different_course=False)
        in_b = self.make_for(section_b, "Same Course - Section B")
        response = self.directory(section=str(self.section.pk))
        ids = list(response.context["assignments"].values_list("pk", flat=True))
        self.assertIn(self.assignment.pk, ids)
        self.assertNotIn(in_b.pk, ids)
        self.assertContains(response, self.section.code)

    def test_teacher_draft_published_and_closed_status_filters(self):
        draft = self.make_for(self.offering, "Private Draft", status=Assignment.Status.DRAFT)
        closed = self.make_for(self.offering, "Completed Topic", status=Assignment.Status.CLOSED)
        response = self.directory(status="draft")
        ids = list(response.context["assignments"].values_list("pk", flat=True))
        self.assertIn(draft.pk, ids)
        self.assertNotIn(self.assignment.pk, ids)
        self.assertNotIn(closed.pk, ids)
        self.assertEqual(response.context["summary"]["draft"], 1)
        self.assertEqual(response.context["summary"]["closed"], 1)

    def test_search_is_scoped_to_owner_and_course_text(self):
        response = self.directory(q="Python")
        self.assertIn(self.assignment.pk, response.context["assignments"].values_list("pk", flat=True))
        response = self.directory(q="Database Assignment")
        self.assertEqual(response.context["filtered_count"], 0)

    def test_student_only_sees_published_authorized_assignments(self):
        self.make_for(self.offering, "Teacher Draft", status=Assignment.Status.DRAFT)
        self.login_as(self.student)
        response = self.client.get(reverse("assignments:list"), {"status": "draft"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_create"])
        self.assertFalse(response.context["show_progress"])
        self.assertFalse(
            response.context["assignments"].filter(status=Assignment.Status.DRAFT).exists()
        )
        choices = response.context["course_choices"]
        self.assertTrue(all(choice["id"] == self.course.pk for choice in choices))
        self.assertNotContains(response, "Teacher Draft")

    def test_course_year_and_term_filters(self):
        response = self.directory(course=str(self.course.pk), year="2026-2027", term="FALL")
        self.assertEqual(response.context["filtered_count"], 1)
        response = self.directory(year="2024-2025")
        self.assertEqual(response.context["filtered_count"], 0)

    def test_pagination_twelve_per_page_and_filters_persist(self):
        for i in range(16):
            self.make_for(self.offering, f"Pagination Example {i:02}")
        first_page = self.directory(sort="course", page="1")
        self.assertEqual(first_page.context["filtered_count"], 17)
        self.assertEqual(len(first_page.context["page_assignments"]), 12)
        self.assertTrue(first_page.context["page_obj"].has_next())
        self.assertIn("sort=course", first_page.context["page_urls"]["next"])
        second_page = self.directory(sort="course", page="2")
        self.assertEqual(len(second_page.context["page_assignments"]), 5)

    def test_edit_not_advertised_after_final_submission(self):
        self.make_submission(
            status=Submission.Status.SUBMITTED,
            text="A valid submitted student answer for the course.",
        )
        response = self.directory()
        # The card detail link remains, but the edit link is suppressed.
        self.assertNotContains(
            response,
            reverse("assignments:edit", args=[self.assignment.pk]),
        )
        self.assertContains(response, "Submissions")

    def test_admin_sees_both_teachers_but_cannot_create(self):
        self.login_as(self.admin)
        response = self.client.get(reverse("assignments:list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Python Assignment")
        self.assertContains(response, "Database Assignment")
        self.assertFalse(response.context["can_create"])
        self.assertTrue(response.context["show_progress"])

    def test_invalid_filters_do_not_crash_and_do_not_expand_access(self):
        response = self.directory(
            course="not-a-number", section="-1", semester="!",
            status="INVALID", sort="invalid", page="not-a-page",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_status"], "all")
        self.assertEqual(response.context["selected_sort"], "newest")
        self.assertNotContains(response, "Database Assignment")

    def test_due_soon_and_overdue_status(self):
        soon = self.make_for(self.offering, "Due Within Week")
        soon.deadline = timezone.now() + timedelta(days=2)
        soon.save(update_fields=["deadline"])
        old = self.make_for(self.offering, "Late Work")
        old.deadline = timezone.now() - timedelta(days=1)
        # Existing assignment model permits a test deadline to be updated via update().
        Assignment.objects.filter(pk=old.pk).update(deadline=old.deadline)
        upcoming = self.directory(status="due_soon")
        self.assertIn(soon.pk, upcoming.context["assignments"].values_list("pk", flat=True))
        self.assertNotIn(old.pk, upcoming.context["assignments"].values_list("pk", flat=True))
        overdue = self.directory(status="overdue")
        self.assertIn(old.pk, overdue.context["assignments"].values_list("pk", flat=True))
        self.assertNotIn(soon.pk, overdue.context["assignments"].values_list("pk", flat=True))
