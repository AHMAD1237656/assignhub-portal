"""Event listeners are additive; existing assignment/OCR signals still run."""

import hashlib
import logging
from django.db import transaction
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from assignments.models import Assignment, Submission
from student_onboarding.models import StudentIdentity
from . import services

logger = logging.getLogger(__name__)


def _after_commit(callback, *args):
    def execute():
        try:
            callback(*args)
        except Exception:
            logger.exception("AssignHub notification delivery failed: %s", callback.__name__)
    transaction.on_commit(execute, robust=True)


@receiver(pre_save, sender=Assignment, dispatch_uid="assignhub.notice.assignment.before")
def assignment_before_save(sender, instance, **kwargs):
    instance._notice_previous_status = (
        sender.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
        if instance.pk else None
    )


@receiver(post_save, sender=Assignment, dispatch_uid="assignhub.notice.assignment.after")
def assignment_after_save(sender, instance, created, update_fields, **kwargs):
    if update_fields is not None and "status" not in update_fields:
        return
    previous = getattr(instance, "_notice_previous_status", None)
    if instance.status == Assignment.Status.PUBLISHED and (created or previous != Assignment.Status.PUBLISHED):
        _after_commit(services.notify_assignment_published, instance.pk)
    elif instance.status == Assignment.Status.CLOSED and previous == Assignment.Status.PUBLISHED:
        _after_commit(services.notify_assignment_closed, instance.pk)


@receiver(pre_save, sender=Submission, dispatch_uid="assignhub.notice.submission.before")
def submission_before_save(sender, instance, **kwargs):
    instance._notice_previous_state = (
        sender.objects.filter(pk=instance.pk).values("status", "marks", "feedback").first()
        if instance.pk else None
    )


@receiver(post_save, sender=Submission, dispatch_uid="assignhub.notice.submission.after")
def submission_after_save(sender, instance, created, update_fields, **kwargs):
    previous = getattr(instance, "_notice_previous_state", None)
    previous_status = previous["status"] if previous else None
    if instance.status == Submission.Status.SUBMITTED:
        if (created or previous_status != Submission.Status.SUBMITTED) and (
            update_fields is None or "status" in update_fields
        ):
            _after_commit(services.notify_submission_received, instance.pk)
    elif instance.status == Submission.Status.GRADED:
        changed = (
            created or previous_status != Submission.Status.GRADED or
            (previous is not None and (
                previous["marks"] != instance.marks or
                previous["feedback"] != instance.feedback
            ))
        )
        if changed and (update_fields is None or bool({"status", "marks", "feedback"} & set(update_fields))):
            # Distinguishes deliberate grade revisions, without repeat-on-read alerts.
            snapshot = f"{instance.pk}|{instance.marks}|{instance.feedback}|{instance.updated_at.isoformat() if instance.updated_at else ''}"
            key = "grade:" + hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
            _after_commit(services.notify_grade_available, instance.pk, key)


@receiver(pre_save, sender=StudentIdentity, dispatch_uid="assignhub.notice.activation.before")
def activation_before_save(sender, instance, **kwargs):
    instance._notice_previous_status = (
        sender.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
        if instance.pk else None
    )


@receiver(post_save, sender=StudentIdentity, dispatch_uid="assignhub.notice.activation.after")
def activation_after_save(sender, instance, created, update_fields, **kwargs):
    if not created and instance.status == StudentIdentity.Status.ACTIVE:
        if getattr(instance, "_notice_previous_status", None) != StudentIdentity.Status.ACTIVE:
            if update_fields is None or "status" in update_fields:
                _after_commit(services.notify_student_activated, instance.pk)
