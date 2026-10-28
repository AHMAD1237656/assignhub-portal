import json
from datetime import timedelta

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from assignments.models import Submission
from assignments.tests import AssignmentTestBase
from courses.models import CourseEnrollment

from .models import (
    TimedWritingAttempt,
    TimedWritingConfig,
)


class TimedWritingTests(AssignmentTestBase):

    def setUp(self):
        super().setUp()

        self.config = TimedWritingConfig.objects.create(
            assignment=self.assignment,
            duration_minutes=30,
            is_enabled=True,
        )

    def url(self, name):
        return reverse(
            f"timed_writing:{name}",
            kwargs={
                "assignment_pk": self.assignment.pk,
            },
        )

    def as_student(self):
        self.login_as(self.student)

    def begin(self):
        self.as_student()

        result = self.client.post(
            self.url("start")
        )

        self.assertEqual(
            result.status_code,
            302,
        )

        return TimedWritingAttempt.objects.get(
            config=self.config,
            student=self.student,
        )

    def save_request(
        self,
        text,
        revision=0,
        action="save",
    ):
        return self.client.post(
            self.url("save"),
            data=json.dumps({
                "answer": text,
                "revision": revision,
                "action": action,
            }),
            content_type="application/json",
        )

    # =========================================
    # TEACHER CONFIGURATION
    # =========================================

    def test_teacher_can_open_config(self):
        self.login_as(self.teacher)

        response = self.client.get(
            self.url("configure")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_teacher_can_update_duration_before_attempt(self):
        self.login_as(self.teacher)

        response = self.client.post(
            self.url("configure"),
            {
                "duration_minutes": 45,
                "is_enabled": "on",
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.config.refresh_from_db()

        self.assertEqual(
            self.config.duration_minutes,
            45,
        )

    def test_teacher_cannot_configure_other_teacher(self):
        self.login_as(self.teacher2)

        response = self.client.get(
            self.url("configure")
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_student_cannot_configure(self):
        self.as_student()

        response = self.client.post(
            self.url("configure"),
            {
                "duration_minutes": 1,
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_admin_cannot_configure_as_teacher(self):
        self.login_as(self.admin)

        response = self.client.get(
            self.url("configure")
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_invalid_duration_rejected(self):
        self.login_as(self.teacher)

        for duration in [
            0,
            -1,
            241,
            "bad",
        ]:

            with self.subTest(duration=duration):

                response = self.client.post(
                    self.url("configure"),
                    {
                        "duration_minutes": duration,
                        "is_enabled": "on",
                    },
                )

                self.assertEqual(
                    response.status_code,
                    200,
                )

                self.assertIn(
                    "duration_minutes",
                    response.context["form"].errors,
                )

    # =========================================
    # STUDENT START & ACCESS
    # =========================================

    def test_student_can_start_one_attempt(self):
        attempt = self.begin()

        self.assertEqual(
            attempt.status,
            TimedWritingAttempt.Status.ACTIVE,
        )

        self.assertEqual(
            attempt.submission.status,
            Submission.Status.DRAFT,
        )

        self.assertEqual(
            attempt.submission.assignment,
            self.assignment,
        )

        self.assertEqual(
            attempt.submission.student,
            self.student,
        )

    def test_duplicate_start_reuses_existing_attempt_and_timer(self):
        attempt = self.begin()

        old_expiry = attempt.expires_at

        response = self.client.post(
            self.url("start")
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertEqual(
            TimedWritingAttempt.objects.filter(
                student=self.student,
            ).count(),
            1,
        )

        attempt.refresh_from_db()

        self.assertEqual(
            attempt.expires_at,
            old_expiry,
        )

    def test_refresh_does_not_reset_expiry(self):
        attempt = self.begin()

        response = self.client.get(
            self.url("editor")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        attempt.refresh_from_db()

        expected_expiry = min(
            attempt.started_at
            + timedelta(minutes=30),
            self.assignment.deadline,
        )

        self.assertEqual(
            attempt.expires_at,
            expected_expiry,
        )

    def test_unenrolled_student_cannot_start(self):
        self.enrollment.delete()

        self.as_student()

        response = self.client.post(
            self.url("start")
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertFalse(
            TimedWritingAttempt.objects.exists()
        )

    def test_dropped_student_cannot_start(self):
        self.enrollment.status = (
            CourseEnrollment.Status.DROPPED
        )

        self.enrollment.save(
            update_fields=["status"]
        )

        self.as_student()

        response = self.client.post(
            self.url("start")
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_wrong_teacher_cannot_start(self):
        self.login_as(self.teacher2)

        response = self.client.post(
            self.url("start")
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_anonymous_redirected(self):
        response = self.client.get(
            self.url("editor")
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        response = self.client.post(
            self.url("start")
        )

        self.assertEqual(
            response.status_code,
            302,
        )

    def test_disabled_mode_cannot_start(self):
        self.config.is_enabled = False
        self.config.save()

        self.as_student()

        response = self.client.post(
            self.url("start")
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_expired_assignment_cannot_start(self):
        self.assignment.deadline = (
            timezone.now()
            - timedelta(minutes=1)
        )

        self.assignment.save()

        self.as_student()

        response = self.client.post(
            self.url("start")
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    # =========================================
    # AUTOSAVE & REVISION PROTECTION
    # =========================================

    def test_autosave_persists_draft(self):
        attempt = self.begin()

        response = self.save_request(
            "Saved answer",
            0,
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        attempt.submission.refresh_from_db()
        attempt.refresh_from_db()

        self.assertEqual(
            attempt.submission.text_content,
            "Saved answer",
        )

        self.assertEqual(
            attempt.submission.status,
            Submission.Status.DRAFT,
        )

        self.assertEqual(
            attempt.revision,
            1,
        )

    def test_stale_revision_cannot_overwrite(self):
        attempt = self.begin()

        response = self.save_request(
            "First",
            0,
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        response = self.save_request(
            "Stale",
            0,
        )

        self.assertEqual(
            response.status_code,
            409,
        )

        attempt.submission.refresh_from_db()

        self.assertEqual(
            attempt.submission.text_content,
            "First",
        )

    # =========================================
    # FINAL SUBMISSION
    # =========================================

    def test_final_submission_uses_existing_submission(self):
        attempt = self.begin()

        submission_pk = attempt.submission_id

        response = self.save_request(
            "My final answer",
            0,
            "finish",
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        attempt.refresh_from_db()
        attempt.submission.refresh_from_db()

        self.assertEqual(
            attempt.status,
            TimedWritingAttempt.Status.SUBMITTED,
        )

        self.assertEqual(
            attempt.submission.status,
            Submission.Status.SUBMITTED,
        )

        self.assertIsNotNone(
            attempt.submission.submitted_at
        )

        self.assertEqual(
            attempt.submission_id,
            submission_pk,
        )

        self.assertEqual(
            Submission.objects.filter(
                assignment=self.assignment,
                student=self.student,
            ).count(),
            1,
        )

    def test_empty_final_submission_rejected(self):
        attempt = self.begin()

        response = self.save_request(
            "   ",
            0,
            "finish",
        )

        self.assertEqual(
            response.status_code,
            400,
        )

        attempt.refresh_from_db()

        self.assertEqual(
            attempt.status,
            TimedWritingAttempt.Status.ACTIVE,
        )

    def test_post_finalize_cannot_edit(self):
        attempt = self.begin()

        response = self.save_request(
            "Final answer",
            0,
            "finish",
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        response = self.save_request(
            "Tampered",
            1,
        )

        self.assertEqual(
            response.status_code,
            409,
        )

        attempt.submission.refresh_from_db()

        self.assertEqual(
            attempt.submission.text_content,
            "Final answer",
        )

    # =========================================
    # TIMER EXPIRATION
    # =========================================

    def test_auto_finalize_saved_answer_at_deadline(self):
        attempt = self.begin()

        self.save_request(
            "Autosaved answer",
            0,
        )

        expired_at = (
            timezone.now()
            - timedelta(seconds=5)
        )

        TimedWritingAttempt.objects.filter(
            pk=attempt.pk
        ).update(
            expires_at=expired_at
        )

        response = self.client.get(
            self.url("status")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        attempt.refresh_from_db()
        attempt.submission.refresh_from_db()

        self.assertTrue(
            attempt.auto_submitted
        )

        self.assertEqual(
            attempt.status,
            TimedWritingAttempt.Status.SUBMITTED,
        )

        self.assertEqual(
            attempt.submission.submitted_at,
            expired_at,
        )

        self.assertEqual(
            attempt.submission.text_content,
            "Autosaved answer",
        )

    def test_expired_empty_attempt_is_not_submitted(self):
        attempt = self.begin()

        TimedWritingAttempt.objects.filter(
            pk=attempt.pk
        ).update(
            expires_at=(
                timezone.now()
                - timedelta(seconds=1)
            )
        )

        response = self.client.get(
            self.url("status")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        attempt.refresh_from_db()
        attempt.submission.refresh_from_db()

        self.assertEqual(
            attempt.status,
            TimedWritingAttempt.Status.EXPIRED,
        )

        self.assertEqual(
            attempt.submission.status,
            Submission.Status.DRAFT,
        )

    def test_after_expiry_late_answer_rejected(self):
        attempt = self.begin()

        TimedWritingAttempt.objects.filter(
            pk=attempt.pk
        ).update(
            expires_at=(
                timezone.now()
                - timedelta(seconds=1)
            )
        )

        response = self.save_request(
            "Too late",
            0,
        )

        self.assertEqual(
            response.status_code,
            409,
        )

        attempt.submission.refresh_from_db()

        self.assertEqual(
            attempt.submission.text_content,
            "",
        )

    # =========================================
    # CONFIGURATION LOCKING
    # =========================================

    def test_config_locked_after_start(self):
        self.begin()

        self.login_as(self.teacher)

        response = self.client.post(
            self.url("configure"),
            {
                "duration_minutes": 45,
                "is_enabled": "on",
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.config.refresh_from_db()

        self.assertEqual(
            self.config.duration_minutes,
            30,
        )

    def test_existing_regular_submission_cannot_be_reconfigured(self):
        self.config.delete()

        self.make_submission()

        self.login_as(self.teacher)

        response = self.client.post(
            self.url("configure"),
            {
                "duration_minutes": 5,
                "is_enabled": "on",
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertFalse(
            TimedWritingConfig.objects.filter(
                assignment=self.assignment,
            ).exists()
        )

    # =========================================
    # STANDARD SUBMISSION BYPASS
    # =========================================

    def test_standard_submission_get_redirects_to_editor(self):
        self.as_student()

        response = self.client.get(
            self.submit_url()
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertIn(
            self.url("editor"),
            response.url,
        )

    def test_standard_submission_post_is_blocked(self):
        self.as_student()

        response = self.client.post(
            self.submit_url(),
            {
                "text_content": "Bypass",
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertFalse(
            Submission.objects.filter(
                student=self.student,
                assignment=self.assignment,
            ).exists()
        )

    # =========================================
    # CSRF & INPUT VALIDATION
    # =========================================

    def test_csrf_required_for_autosave(self):
        self.begin()

        secure = Client(
            enforce_csrf_checks=True
        )

        secure.force_login(
            self.student
        )

        response = secure.post(
            self.url("save"),
            data=json.dumps({
                "answer": "No csrf",
                "revision": 0,
            }),
            content_type="application/json",
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_malformed_payload_rejected(self):
        self.begin()

        invalid_data = [
            {
                "answer": "x",
                "revision": True,
            },
            {
                "answer": 123,
                "revision": 0,
            },
            {
                "answer": "x",
                "revision": -1,
            },
            {
                "answer": "x",
                "revision": 0,
                "action": "override",
            },
        ]

        for data in invalid_data:

            with self.subTest(data=data):

                response = self.client.post(
                    self.url("save"),
                    data=json.dumps(data),
                    content_type="application/json",
                )

                self.assertEqual(
                    response.status_code,
                    400,
                )

    def test_overlong_answer_rejected(self):
        self.begin()

        response = self.save_request(
            "x" * 100_001
        )

        self.assertEqual(
            response.status_code,
            400,
        )

    # =========================================
    # STUDENT DATA ISOLATION
    # =========================================

    def test_another_enrolled_student_cannot_read_my_draft(self):
        self.begin()

        response = self.save_request(
            "My private draft"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.login_as(self.student2)

        response = self.client.get(
            self.url("editor")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertNotContains(
            response,
            "My private draft",
        )

        response = self.client.get(
            self.url("status")
        )

        self.assertEqual(
            response.status_code,
            404,
        )

    # =========================================
    # EXISTING GRADING INTEGRATION
    # =========================================

    def test_grade_normal_workflow_after_timed_submission(self):
        attempt = self.begin()

        response = self.save_request(
            "Final answer",
            0,
            "finish",
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.login_as(self.teacher)

        response = self.client.get(
            self.review_url(
                attempt.submission
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        response = self.client.post(
            self.review_url(
                attempt.submission
            ),
            {
                "marks": "87",
                "feedback": "Good",
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        attempt.submission.refresh_from_db()

        self.assertEqual(
            attempt.submission.status,
            Submission.Status.GRADED,
        )

    # =========================================
    # ENROLLMENT SECURITY
    # =========================================

    def test_dropped_student_cannot_save_after_start(self):
        self.begin()

        self.enrollment.status = (
            CourseEnrollment.Status.DROPPED
        )

        self.enrollment.save(
            update_fields=["status"]
        )

        response = self.save_request(
            "No longer enrolled"
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    # =========================================
    # ASSIGNMENT EDIT / CLOSE SECURITY
    # =========================================

    def test_teacher_cannot_edit_after_attempt_starts(self):
        self.begin()

        self.login_as(self.teacher)

        response = self.client.get(
            reverse(
                "assignments:edit",
                args=[self.assignment.pk],
            )
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_teacher_cannot_close_with_active_attempt(self):
        self.begin()

        self.login_as(self.teacher)

        response = self.client.post(
            reverse(
                "assignments:close",
                args=[self.assignment.pk],
            )
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    # =========================================
    # STATUS ENDPOINT SECURITY
    # =========================================

    def test_unauthorized_status_no_data_leak(self):
        self.begin()

        self.login_as(self.teacher2)

        response = self.client.get(
            self.url("status")
        )

        self.assertEqual(
            response.status_code,
            403,
        )

import json
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from assignments.models import Submission
from assignments.tests import AssignmentTestBase

from .models import (
    TimedWritingAttempt,
    TimedWritingConfig,
)
from .richtext import normalize_delta


class RichEditorValidationTests(AssignmentTestBase):

    def test_bold_format_is_preserved(self):
        delta = {
            "ops": [
                {
                    "insert": "Important answer",
                    "attributes": {
                        "bold": True,
                    },
                },
                {
                    "insert": "\n",
                },
            ]
        }

        cleaned, text = normalize_delta(delta)

        self.assertEqual(
            cleaned["ops"][0]["attributes"]["bold"],
            True,
        )

        self.assertIn(
            "Important answer",
            text,
        )

    def test_formula_is_preserved(self):
        delta = {
            "ops": [
                {
                    "insert": {
                        "formula": r"\frac{a}{b}"
                    }
                },
                {
                    "insert": "\n"
                },
            ]
        }

        cleaned, text = normalize_delta(delta)

        self.assertEqual(
            cleaned["ops"][0]["insert"]["formula"],
            r"\frac{a}{b}",
        )

        self.assertIn(
            "Formula:",
            text,
        )

    def test_shape_is_preserved(self):
        delta = {
            "ops": [
                {
                    "insert": {
                        "shape": {
                            "kind": "rectangle",
                            "label": "Start",
                        }
                    }
                },
                {
                    "insert": "\n"
                },
            ]
        }

        cleaned, text = normalize_delta(delta)

        self.assertEqual(
            cleaned["ops"][0]["insert"]["shape"]["kind"],
            "rectangle",
        )

        self.assertIn(
            "Start",
            text,
        )

    def test_image_embed_is_rejected(self):
        delta = {
            "ops": [
                {
                    "insert": {
                        "image": "javascript:alert(1)"
                    }
                }
            ]
        }

        with self.assertRaises(ValidationError):
            normalize_delta(delta)

    def test_javascript_link_is_rejected(self):
        delta = {
            "ops": [
                {
                    "insert": "Click here",
                    "attributes": {
                        "link": "javascript:alert(1)",
                    },
                }
            ]
        }

        with self.assertRaises(ValidationError):
            normalize_delta(delta)

    def test_invalid_document_operation_rejected(self):
        delta = {
            "ops": [
                {
                    "delete": 5
                }
            ]
        }

        with self.assertRaises(ValidationError):
            normalize_delta(delta)


class RichEditorIntegrationTests(AssignmentTestBase):

    def setUp(self):
        super().setUp()

        self.config = (
            TimedWritingConfig.objects.create(
                assignment=self.assignment,
                duration_minutes=30,
                is_enabled=True,
            )
        )

        self.login_as(self.student)

        response = self.client.post(
            reverse(
                "timed_writing:start",
                kwargs={
                    "assignment_pk": self.assignment.pk
                },
            )
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.attempt = (
            TimedWritingAttempt.objects.get(
                config=self.config,
                student=self.student,
            )
        )

    def rich_save(
        self,
        delta,
        revision=0,
        action="save",
    ):
        return self.client.post(
            reverse(
                "timed_writing:save",
                kwargs={
                    "assignment_pk": self.assignment.pk
                },
            ),
            data=json.dumps({
                "answer": "Ignored client-side text",
                "delta": delta,
                "revision": revision,
                "action": action,
            }),
            content_type="application/json",
        )

    def test_rich_autosave_updates_existing_submission(self):
        delta = {
            "ops": [
                {
                    "insert": "Hello World",
                    "attributes": {
                        "bold": True
                    },
                },
                {
                    "insert": "\n"
                },
            ]
        }

        response = self.rich_save(delta)

        self.assertEqual(
            response.status_code,
            200,
        )

        self.attempt.refresh_from_db()
        self.attempt.submission.refresh_from_db()

        self.assertEqual(
            self.attempt.rich_delta["ops"][0]["attributes"]["bold"],
            True,
        )

        self.assertIn(
            "Hello World",
            self.attempt.submission.text_content,
        )

        self.assertNotIn(
            "Ignored client-side text",
            self.attempt.submission.text_content,
        )

    def test_rich_formula_final_submission(self):
        delta = {
            "ops": [
                {
                    "insert": "Pythagoras: "
                },
                {
                    "insert": {
                        "formula": r"a^2+b^2=c^2"
                    }
                },
                {
                    "insert": "\n"
                },
            ]
        }

        response = self.rich_save(
            delta,
            action="finish",
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.attempt.refresh_from_db()
        self.attempt.submission.refresh_from_db()

        self.assertEqual(
            self.attempt.status,
            TimedWritingAttempt.Status.SUBMITTED,
        )

        self.assertEqual(
            self.attempt.submission.status,
            Submission.Status.SUBMITTED,
        )

        self.assertIn(
            "[Formula:",
            self.attempt.submission.text_content,
        )

    def test_stale_rich_revision_cannot_overwrite(self):
        first = {
            "ops": [
                {"insert": "Version One\n"}
            ]
        }

        second = {
            "ops": [
                {"insert": "Version Two\n"}
            ]
        }

        response = self.rich_save(first)

        self.assertEqual(
            response.status_code,
            200,
        )

        response = self.rich_save(
            second,
            revision=0,
        )

        self.assertEqual(
            response.status_code,
            409,
        )

        self.attempt.refresh_from_db()

        self.assertEqual(
            self.attempt.rich_delta,
            first,
        )

    def test_expired_attempt_rejects_rich_save(self):
        TimedWritingAttempt.objects.filter(
            pk=self.attempt.pk
        ).update(
            expires_at=(
                timezone.now()
                - timedelta(seconds=5)
            )
        )

        response = self.rich_save({
            "ops": [
                {"insert": "Late answer\n"}
            ]
        })

        self.assertEqual(
            response.status_code,
            409,
        )

    def test_shape_can_be_finalized(self):
        delta = {
            "ops": [
                {
                    "insert": {
                        "shape": {
                            "kind": "diamond",
                            "label": "Decision",
                        }
                    }
                },
                {
                    "insert": "\n"
                },
            ]
        }

        response = self.rich_save(
            delta,
            action="finish",
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.attempt.submission.refresh_from_db()

        self.assertEqual(
            self.attempt.submission.status,
            Submission.Status.SUBMITTED,
        )