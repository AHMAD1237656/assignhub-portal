from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from timed_writing.models import (
    TimedWritingAttempt,
)
from timed_writing.services import (
    settle_if_expired,
)


class Command(BaseCommand):

    help = (
        "Finalize expired timed writing attempts "
        "using the last saved draft."
    )

    def handle(self, *args, **options):

        ids = list(
            TimedWritingAttempt.objects.filter(
                status=TimedWritingAttempt.Status.ACTIVE,
                expires_at__lte=timezone.now(),
            ).values_list(
                "pk",
                flat=True,
            )
        )

        finished = 0

        for attempt_id in ids:

            with transaction.atomic():

                attempt = (
                    TimedWritingAttempt.objects
                    .select_for_update()
                    .get(pk=attempt_id)
                )

                if (
                    attempt.status
                    == TimedWritingAttempt.Status.ACTIVE
                ):
                    settle_if_expired(attempt)
                    finished += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {finished} expired attempts."
            )
        )