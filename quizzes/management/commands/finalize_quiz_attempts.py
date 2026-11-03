from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from quizzes.models import Quiz, QuizAttempt
from quizzes.services import settle_locked


class Command(BaseCommand):
    help = 'Auto-submit in-progress quizzes after time expiry or teacher closure.'

    def handle(self, *args, **options):
        now = timezone.now()
        ids = QuizAttempt.objects.filter(status=QuizAttempt.Status.IN_PROGRESS).filter(
            Q(expires_at__lte=now) | Q(quiz__status=Quiz.Status.CLOSED)
        ).values_list('pk', flat=True)
        n = 0
        for pk in ids.iterator(chunk_size=200):
            with transaction.atomic():
                attempt = QuizAttempt.objects.select_for_update().select_related('quiz').get(pk=pk)
                if attempt.status == QuizAttempt.Status.IN_PROGRESS:
                    settle_locked(attempt)
                    n += int(attempt.status != QuizAttempt.Status.IN_PROGRESS)
        from quizzes.notice_events import send_released_result_notices
        alerts = send_released_result_notices()
        self.stdout.write(self.style.SUCCESS(f'Finalized {n} quiz attempt(s); sent {alerts} new result notification(s).'))
