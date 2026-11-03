"""Monitoring lifecycle is additive; quiz scoring remains owned by quizzes."""
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from quizzes.models import QuizAttempt
from .models import MonitoringSession


@receiver(post_save, sender=QuizAttempt, dispatch_uid='assignhub.proctoring.close_session')
def on_attempt_finish(sender, instance, created, update_fields, **kwargs):
    if instance.status != QuizAttempt.Status.IN_PROGRESS:
        MonitoringSession.objects.filter(attempt_id=instance.pk, closed_at__isnull=True).update(closed_at=timezone.now())
