"""Additive notification events: no updates to grading, submissions or activation."""

import logging
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from courses.models import CourseEnrollment
from .models import Notification

logger = logging.getLogger(__name__)


def _create(recipient_id, kind, title, message, target_url, event_key):
    if not target_url.startswith("/") or target_url.startswith("//"):
        raise ValueError("Notification target must be an internal path")
    Notification.objects.get_or_create(
        event_key=event_key,
        defaults={
            "recipient_id": recipient_id,
            "kind": kind,
            "title": title[:160],
            "message": message[:350],
            "target_url": target_url[:500],
        },
    )


def _active_students(offering_id):
    return CourseEnrollment.objects.filter(
        offering_id=offering_id,
        status=CourseEnrollment.Status.ACTIVE,
        student__is_active=True,
    ).values_list("student_id", flat=True).distinct()


def _broadcast(recipients, *, kind, title, message, url, event_prefix):
    """Bulk create is idempotent under concurrent retries."""
    unique_ids = set(recipients)
    if not unique_ids:
        return
    Notification.objects.bulk_create([
        Notification(
            recipient_id=student_id, kind=kind,
            title=title[:160], message=message[:350],
            target_url=url, event_key=f"{event_prefix}:{student_id}",
        ) for student_id in unique_ids
    ], ignore_conflicts=True, batch_size=400)


def notify_assignment_published(assignment_id):
    from assignments.models import Assignment
    assignment = Assignment.objects.select_related("course_offering").filter(
        pk=assignment_id, status=Assignment.Status.PUBLISHED
    ).first()
    if not assignment or not assignment.course_offering_id or not assignment.course_offering.is_active:
        return
    _broadcast(
        _active_students(assignment.course_offering_id),
        kind=Notification.Kind.ASSIGNMENT,
        title="New assignment published",
        message=f"{assignment.title} is available. Deadline: {timezone.localtime(assignment.deadline):%d %b %Y, %I:%M %p}.",
        url=reverse("assignments:detail", args=[assignment.pk]),
        event_prefix=f"assignment:published:{assignment.pk}",
    )


def notify_assignment_closed(assignment_id):
    from assignments.models import Assignment
    assignment = Assignment.objects.select_related("course_offering").filter(
        pk=assignment_id, status=Assignment.Status.CLOSED
    ).first()
    if not assignment or not assignment.course_offering_id:
        return
    _broadcast(
        _active_students(assignment.course_offering_id),
        kind=Notification.Kind.ASSIGNMENT_CLOSED,
        title="Assignment closed",
        message=f"{assignment.title} is now closed for submissions.",
        url=reverse("assignments:list"),
        event_prefix=f"assignment:closed:{assignment.pk}",
    )


def notify_submission_received(submission_id):
    from assignments.models import Submission
    submission = Submission.objects.select_related("student", "assignment", "assignment__created_by").filter(
        pk=submission_id, status=Submission.Status.SUBMITTED
    ).first()
    if not submission or not submission.assignment.created_by.is_active:
        return
    student_name = submission.student.get_full_name() or submission.student.username
    _create(
        submission.assignment.created_by_id, Notification.Kind.SUBMISSION,
        "New student submission",
        f"{student_name} submitted {submission.assignment.title}.",
        reverse("assignments:submission_review", args=[submission.pk]),
        f"submission:final:{submission.pk}",
    )


def notify_grade_available(submission_id, event_key):
    from assignments.models import Submission
    submission = Submission.objects.select_related("student", "assignment").filter(
        pk=submission_id, status=Submission.Status.GRADED
    ).first()
    if not submission or not submission.student.is_active:
        return
    _create(
        submission.student_id, Notification.Kind.GRADE,
        "Assignment graded",
        f"Your result for {submission.assignment.title} is available.",
        reverse("assignments:submissions"),
        event_key,
    )


def notify_plagiarism_flag(submission_id):
    """Called only after a flagged result was persisted by the scan worker."""
    from assignments.models import PlagiarismScan
    scan = PlagiarismScan.objects.select_related("submission__assignment__created_by").filter(
        submission_id=submission_id,
        status=PlagiarismScan.Status.NEEDS_REVIEW,
    ).first()
    if not scan or not scan.submission.assignment.created_by.is_active:
        return
    _create(
        scan.submission.assignment.created_by_id,
        Notification.Kind.PLAGIARISM,
        "Plagiarism report needs review",
        f"Potentially matching content found in {scan.submission.assignment.title}. Instructor verification is required.",
        reverse("assignments:auto_scan_report", args=[submission_id]),
        f"plagiarism:flag:{submission_id}",
    )


def notify_student_activated(identity_id):
    """Inform active university admins only; no passwords or tokens in alerts."""
    from student_onboarding.models import StudentIdentity
    identity = StudentIdentity.objects.select_related("user").filter(
        pk=identity_id, status=StudentIdentity.Status.ACTIVE
    ).first()
    if not identity:
        return
    User = get_user_model()
    admins = User.objects.filter(is_active=True).filter(
        Q(is_superuser=True) | Q(is_staff=True, profile__role=UserProfile.Role.ADMIN)
    ).distinct().values_list("pk", flat=True)
    _broadcast(
        admins,
        kind=Notification.Kind.ACTIVATION,
        title="Student account activated",
        message=f"{identity.user.get_full_name() or identity.roll_number} ({identity.roll_number}) activated their account.",
        url=reverse("student_onboarding:student_detail", args=[identity.pk]),
        event_prefix=f"student:activated:{identity.pk}",
    )
