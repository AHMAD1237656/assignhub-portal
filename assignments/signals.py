"""Enqueue on the commit that finalizes an ordinary or timed submission."""

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Submission


@receiver(post_save, sender=Submission, dispatch_uid="assignhub.queue_final_submission")
def queue_final_submission(sender, instance, created, update_fields, **kwargs):
    # Never scan drafts. Grading does not change content and should not requeue.
    if instance.status != Submission.Status.SUBMITTED:
        return
    if not created and update_fields is not None and "status" not in update_fields:
        return

    assignment_id = instance.assignment_id

    def enqueue_after_commit():
        from .auto_plagiarism import queue_assignment
        queue_assignment(assignment_id)

    transaction.on_commit(enqueue_after_commit, robust=True)
