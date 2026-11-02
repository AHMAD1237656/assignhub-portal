"""Role isolation, event transitions, idempotency, and UI coverage."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from assignments.models import Assignment, PlagiarismScan, Submission
from assignments.tests import AssignmentTestBase
from student_onboarding.models import StudentIdentity, StudentImportBatch

from .models import Notification
from .services import notify_plagiarism_flag


class NotificationCenterTests(AssignmentTestBase):
    def test_authenticated_bell_and_center(self):
        self.login_as(self.student)
        response = self.client.get(reverse("notifications:list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Notification Center")
        self.assertContains(response, "ah-notice-bell")
        self.assertEqual(self.client.get(reverse("notifications:count")).json()["unread_count"], 0)

    def test_anonymous_requires_login(self):
        self.assertEqual(self.client.get(reverse("notifications:list")).status_code, 302)
        self.assertEqual(self.client.get(reverse("notifications:count")).status_code, 302)

    def _notice(self, owner=None, key="test:1", url=None):
        return Notification.objects.create(
            recipient=owner or self.student,
            kind=Notification.Kind.GRADE,
            title="Your grade is ready",
            message="Assignment graded",
            target_url=url or reverse("assignments:detail", args=[self.assignment.pk]),
            event_key=key,
        )

    def test_other_student_cannot_open_or_mark_notice(self):
        notice = self._notice()
        self.login_as(self.student2)
        self.assertEqual(self.client.get(reverse("notifications:list")).status_code, 200)
        self.assertNotContains(self.client.get(reverse("notifications:list")), notice.title)
        self.assertEqual(self.client.post(reverse("notifications:open", args=[notice.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("notifications:mark_read", args=[notice.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("notifications:count")).json()["unread_count"], 0)

    def test_open_is_post_only_and_marks_read(self):
        notice = self._notice()
        self.login_as(self.student)
        url = reverse("notifications:open", args=[notice.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url)
        self.assertRedirects(response, reverse("assignments:detail", args=[self.assignment.pk]), fetch_redirect_response=False)
        notice.refresh_from_db()
        self.assertIsNotNone(notice.read_at)
        self.assertEqual(self.client.get(reverse("notifications:count")).json()["unread_count"], 0)

    def test_bad_destination_cannot_redirect_externally(self):
        notice = self._notice(url="//external.example/evil")
        self.login_as(self.student)
        response = self.client.post(reverse("notifications:open", args=[notice.pk]))
        self.assertRedirects(response, reverse("notifications:list"), fetch_redirect_response=False)

    def test_mark_all_and_clear_only_current_users(self):
        self._notice()
        self._notice(owner=self.student2, key="test:2")
        self.login_as(self.student)
        self.assertEqual(self.client.get(reverse("notifications:mark_all_read")).status_code, 405)
        self.client.post(reverse("notifications:mark_all_read"))
        self.assertEqual(Notification.objects.filter(recipient=self.student, read_at__isnull=True).count(), 0)
        self.assertEqual(Notification.objects.filter(recipient=self.student2, read_at__isnull=True).count(), 1)
        self.client.post(reverse("notifications:clear_read"))
        self.assertEqual(Notification.objects.filter(recipient=self.student, archived_at__isnull=True).count(), 0)
        self.assertEqual(Notification.objects.filter(recipient=self.student2, archived_at__isnull=True).count(), 1)
        self.assertTrue(Notification.objects.filter(recipient=self.student).exists())  # dedup key remains

    def test_csrf_is_required_for_write(self):
        notice = self._notice()
        secure_client = Client(enforce_csrf_checks=True)
        secure_client.force_login(self.student)
        self.assertEqual(
            secure_client.post(reverse("notifications:mark_read", args=[notice.pk])).status_code,
            403,
        )

    def test_published_assignment_notifies_only_active_enrollment(self):
        with self.captureOnCommitCallbacks(execute=True):
            new = Assignment.objects.create(
                created_by=self.teacher, course_offering=self.offering,
                title="Fresh academic task", instructions="Complete the questions",
                deadline=timezone.now() + timedelta(days=4), total_marks=20,
                status=Assignment.Status.PUBLISHED,
            )
        self.assertEqual(Notification.objects.filter(kind=Notification.Kind.ASSIGNMENT).count(), 2)
        self.assertFalse(Notification.objects.filter(recipient=self.teacher, kind=Notification.Kind.ASSIGNMENT).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.student, target_url=reverse("assignments:detail", args=[new.pk])).exists())

    def test_draft_then_publish_only_sends_once(self):
        with self.captureOnCommitCallbacks(execute=True):
            new = Assignment.objects.create(
                created_by=self.teacher, course_offering=self.offering,
                title="Initially private", instructions="Complete task",
                deadline=timezone.now() + timedelta(days=5), total_marks=20,
                status=Assignment.Status.DRAFT,
            )
        self.assertFalse(Notification.objects.filter(kind=Notification.Kind.ASSIGNMENT).exists())
        with self.captureOnCommitCallbacks(execute=True):
            new.status = Assignment.Status.PUBLISHED
            new.save(update_fields=["status", "updated_at"])
        self.assertEqual(Notification.objects.filter(kind=Notification.Kind.ASSIGNMENT).count(), 2)
        with self.captureOnCommitCallbacks(execute=True):
            new.save(update_fields=["title", "updated_at"])
        self.assertEqual(Notification.objects.filter(kind=Notification.Kind.ASSIGNMENT).count(), 2)

    def test_submission_notifies_teacher_without_draft_noise(self):
        with self.captureOnCommitCallbacks(execute=True):
            submission = Submission.objects.create(
                assignment=self.assignment, student=self.student,
                status=Submission.Status.DRAFT, text_content="A draft answer",
            )
        self.assertFalse(Notification.objects.filter(kind=Notification.Kind.SUBMISSION).exists())
        with self.captureOnCommitCallbacks(execute=True):
            submission.status = Submission.Status.SUBMITTED
            submission.submitted_at = timezone.now()
            submission.save(update_fields=["status", "submitted_at", "updated_at"])
        notice = Notification.objects.get(kind=Notification.Kind.SUBMISSION)
        self.assertEqual(notice.recipient_id, self.teacher.pk)
        with self.captureOnCommitCallbacks(execute=True):
            submission.save(update_fields=["text_content", "updated_at"])
        self.assertEqual(Notification.objects.filter(kind=Notification.Kind.SUBMISSION).count(), 1)

    def test_grade_notifies_student_and_revision_notifies_again(self):
        with self.captureOnCommitCallbacks(execute=True):
            submission = self.make_submission()
        with self.captureOnCommitCallbacks(execute=True):
            submission.status = Submission.Status.GRADED
            submission.marks = 80
            submission.feedback = "Well done"
            submission.save(update_fields=["status", "marks", "feedback", "updated_at"])
        self.assertEqual(Notification.objects.filter(kind=Notification.Kind.GRADE, recipient=self.student).count(), 1)
        with self.captureOnCommitCallbacks(execute=True):
            submission.save(update_fields=["marks", "updated_at"])
        self.assertEqual(Notification.objects.filter(kind=Notification.Kind.GRADE).count(), 1)
        with self.captureOnCommitCallbacks(execute=True):
            submission.marks = 87
            submission.save(update_fields=["marks", "updated_at"])
        self.assertEqual(Notification.objects.filter(kind=Notification.Kind.GRADE).count(), 2)

    def test_flagged_report_notifies_teacher_once(self):
        with self.captureOnCommitCallbacks(execute=True):
            sub = self.make_submission()
        PlagiarismScan.objects.filter(submission=sub).update(status=PlagiarismScan.Status.NEEDS_REVIEW)
        notify_plagiarism_flag(sub.pk)
        notify_plagiarism_flag(sub.pk)
        notice = Notification.objects.get(kind=Notification.Kind.PLAGIARISM)
        self.assertEqual(notice.recipient_id, self.teacher.pk)
        self.assertEqual(notice.target_url, reverse("assignments:auto_scan_report", args=[sub.pk]))

    def test_deadline_reminder_idempotent_and_skips_submitted(self):
        Assignment.objects.filter(pk=self.assignment.pk).update(
            deadline=timezone.now() + timedelta(hours=12)
        )
        call_command("send_deadline_notifications", verbosity=0)
        call_command("send_deadline_notifications", verbosity=0)
        self.assertEqual(Notification.objects.filter(kind=Notification.Kind.DEADLINE).count(), 2)
        self.assertFalse(Notification.objects.filter(recipient=self.teacher, kind=Notification.Kind.DEADLINE).exists())

    def test_admin_gets_student_activation_notice(self):
        batch = StudentImportBatch.objects.create(
            created_by=self.admin, filename="students.csv", section=self.section,
            academic_year="2026-2027", term="FALL",
            status=StudentImportBatch.Status.CONFIRMED,
        )
        with self.captureOnCommitCallbacks(execute=True):
            identity = StudentIdentity.objects.create(
                user=self.student, import_batch=batch, roll_number="2026-TEST-01",
                institutional_email="teststudent@uni.example", section=self.section,
                academic_year="2026-2027", term="FALL",
                status=StudentIdentity.Status.PENDING,
            )
            identity.status = StudentIdentity.Status.ACTIVE
            identity.activated_at = timezone.now()
            identity.save(update_fields=["status", "activated_at"])
        self.assertTrue(Notification.objects.filter(
            recipient=self.admin, kind=Notification.Kind.ACTIVATION,
        ).exists())
