"""Regression checks for the targeted AssignHub display fixes."""
from decimal import Decimal

from django.urls import reverse

from .models import Submission
from .tests import AssignmentTestBase


class RequiredHardeningAssignmentTests(AssignmentTestBase):
    def test_student_sees_graded_marks_in_submission_directory(self):
        self.make_submission(
            student=self.student, status=Submission.Status.GRADED,
            marks=Decimal("73.00"),
        )
        self.login_as(self.student)
        response = self.client.get(reverse("assignments:submissions"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "73.00")
        self.assertNotContains(response, "Pending release")

    def test_detail_does_not_offer_edit_after_timed_attempt(self):
        from timed_writing.models import TimedWritingConfig, TimedWritingAttempt

        cfg = TimedWritingConfig.objects.create(
            assignment=self.assignment, is_enabled=True,
            duration_minutes=15,
        )
        draft = self.make_submission(
            student=self.student, status=Submission.Status.DRAFT,
        )
        TimedWritingAttempt.objects.create(
            config=cfg, student=self.student, submission=draft,
        )
        self.login_as(self.teacher)
        response = self.client.get(reverse("assignments:detail", args=[self.assignment.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response, 'href="' + reverse("assignments:edit", args=[self.assignment.pk]) + '"'
        )
