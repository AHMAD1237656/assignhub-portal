"""Quiz publication / submission transitions -> in-app notifications."""

import logging

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Quiz, QuizAttempt
from . import notice_events

logger = logging.getLogger(__name__)


def _on_commit(fn, *args):
    def deliver():
        try:
            fn(*args)
        except Exception:
            logger.exception('Quiz notification delivery failed: %s', fn.__name__)
    transaction.on_commit(deliver, robust=True)


@receiver(pre_save, sender=Quiz, dispatch_uid='assignhub.quizzes.notice.before')
def before_quiz_save(sender, instance, **kwargs):
    instance._ahq_previous = (
        sender.objects.filter(pk=instance.pk).values('status', 'show_results').first()
        if instance.pk else None
    )


@receiver(post_save, sender=Quiz, dispatch_uid='assignhub.quizzes.notice.after')
def after_quiz_save(sender, instance, created, update_fields, **kwargs):
    changed_fields = set(update_fields) if update_fields is not None else None
    old = getattr(instance, '_ahq_previous', None)
    prev_status = old['status'] if old else None
    if (changed_fields is None or 'status' in changed_fields):
        if instance.status == Quiz.Status.PUBLISHED and prev_status != Quiz.Status.PUBLISHED:
            _on_commit(notice_events.quiz_published, instance.pk)
        if instance.status == Quiz.Status.CLOSED and prev_status != Quiz.Status.CLOSED:
            _on_commit(notice_events.quiz_results_released, instance.pk)
    if (changed_fields is None or 'show_results' in changed_fields):
        if instance.show_results and old is not None and not old['show_results']:
            _on_commit(notice_events.quiz_results_released, instance.pk)


@receiver(post_save, sender=QuizAttempt, dispatch_uid='assignhub.quizzes.notice.attempt')
def after_attempt_save(sender, instance, created, update_fields, **kwargs):
    if instance.status not in [QuizAttempt.Status.SUBMITTED, QuizAttempt.Status.AUTO_SUBMITTED]:
        return
    if update_fields is not None and 'status' not in update_fields:
        return
    # Unique event keys guarantee one alert per completed attempt on retry.
    _on_commit(notice_events.attempt_completed, instance.pk)
