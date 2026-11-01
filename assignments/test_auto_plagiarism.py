"""Regression tests for submission-triggered, persisted auto-scan workflow."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile

from .auto_plagiarism import process_next
from .models import Assignment, PlagiarismScan, Submission


TEXT = (
    "A relational database stores information using connected tables. "
    "A primary key uniquely identifies each record. A foreign key "
    "connects related tables and normalization reduces duplicate data. "
    "Database transactions keep changes consistent when many users "
    "access the same information at the same time."
)


class AutomaticScanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.teacher = User.objects.create_user(
            username="scan_teacher", password="ValidPass123!"
        )
        cls.other_teacher = User.objects.create_user(
            username="other_scan_teacher", password="ValidPass123!"
        )
        cls.students = [
            User.objects.create_user(username=f"scan_student_{i}")
            for i in range(3)
        ]
        for teacher in [cls.teacher, cls.other_teacher]:
            UserProfile.objects.create(
                user=teacher, role=UserProfile.Role.TEACHER
            )
        for student in cls.students:
            UserProfile.objects.create(
                user=student, role=UserProfile.Role.STUDENT
            )
        cls.assignment = Assignment.objects.create(
            created_by=cls.teacher,
            title="Auto scan scenario",
            instructions="Explain relational databases",
            deadline=timezone.now() + timedelta(days=5),
            status=Assignment.Status.DRAFT,
            total_marks=100,
        )
        cls.other_assignment = Assignment.objects.create(
            created_by=cls.teacher,
            title="Unrelated assignment",
            instructions="Explain networking",
            deadline=timezone.now() + timedelta(days=5),
            status=Assignment.Status.DRAFT,
            total_marks=100,
        )

    def submit(self, student, text=TEXT, assignment=None):
        with self.captureOnCommitCallbacks(execute=True):
            return Submission.objects.create(
                assignment=assignment or self.assignment,
                student=student,
                status=Submission.Status.SUBMITTED,
                submitted_at=timezone.now(),
                text_content=text,
            )

    def test_first_waits_and_second_requeues_both(self):
        first = self.submit(self.students[0])
        self.assertTrue(process_next())
        first_scan = PlagiarismScan.objects.get(submission=first)
        self.assertEqual(first_scan.status, PlagiarismScan.Status.WAITING)
        second = self.submit(self.students[1])
        first_scan.refresh_from_db()
        self.assertEqual(first_scan.status, PlagiarismScan.Status.QUEUED)
        self.assertTrue(process_next())
        self.assertTrue(process_next())
        first_scan.refresh_from_db()
        second_scan = PlagiarismScan.objects.get(submission=second)
        self.assertEqual(first_scan.status, PlagiarismScan.Status.NEEDS_REVIEW)
        self.assertEqual(second_scan.status, PlagiarismScan.Status.NEEDS_REVIEW)
        self.assertEqual(first_scan.highest_lexical, 100)
        self.assertEqual(second_scan.highest_lexical, 100)
        self.assertEqual(first_scan.checked_count, 1)

    def test_other_assignment_is_excluded(self):
        first = self.submit(self.students[0])
        self.submit(self.students[1], assignment=self.other_assignment)
        self.assertTrue(process_next())
        self.assertTrue(process_next())
        self.assertEqual(
            PlagiarismScan.objects.get(submission=first).status,
            PlagiarismScan.Status.WAITING,
        )

    def test_grade_does_not_requeue(self):
        first = self.submit(self.students[0])
        self.assertTrue(process_next())
        report = PlagiarismScan.objects.get(submission=first)
        current_version = report.version
        with self.captureOnCommitCallbacks(execute=True):
            first.status = Submission.Status.GRADED
            first.marks = 80
            first.save(update_fields=["status", "marks", "updated_at"])
        report.refresh_from_db()
        self.assertEqual(report.version, current_version)
        self.assertEqual(report.status, PlagiarismScan.Status.WAITING)

    def test_report_and_retry_are_teacher_only(self):
        first = self.submit(self.students[0])
        report_url = reverse("assignments:auto_scan_report", args=[first.pk])
        retry_url = reverse("assignments:auto_scan_retry", args=[first.pk])

        self.client.force_login(self.students[0])
        self.assertEqual(self.client.get(report_url).status_code, 403)
        self.assertEqual(self.client.post(retry_url).status_code, 403)
        self.client.force_login(self.other_teacher)
        self.assertEqual(self.client.get(report_url).status_code, 403)

        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(report_url).status_code, 200)
        self.assertEqual(self.client.post(retry_url).status_code, 302)
        self.assertEqual(
            PlagiarismScan.objects.get(submission=first).status,
            PlagiarismScan.Status.QUEUED,
        )

    def test_draft_to_final_status_change_queues_scan(self):
        # Same save(update_fields=...) pattern used by timed-writing finalize.
        draft = Submission.objects.create(
            assignment=self.assignment,
            student=self.students[0],
            status=Submission.Status.DRAFT,
            text_content=TEXT,
        )
        with self.captureOnCommitCallbacks(execute=True):
            draft.status = Submission.Status.SUBMITTED
            draft.submitted_at = timezone.now()
            draft.save(update_fields=["status", "submitted_at", "updated_at"])
        self.assertEqual(
            PlagiarismScan.objects.get(submission=draft).status,
            PlagiarismScan.Status.QUEUED,
        )

    def test_draft_does_not_enqueue(self):
        draft = Submission.objects.create(
            assignment=self.assignment,
            student=self.students[0],
            status=Submission.Status.DRAFT,
            text_content=TEXT,
        )
        self.assertFalse(PlagiarismScan.objects.filter(submission=draft).exists())
