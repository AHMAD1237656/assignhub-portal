from django.core.management.base import BaseCommand

from student_onboarding.models import StudentImportBatch
from student_onboarding.services import (
    send_pending_activation_emails,
)


class Command(BaseCommand):
    help = (
        "Send activation emails for a confirmed "
        "student import batch."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-id",
            type=int,
            required=True,
            help="Confirmed StudentImportBatch ID",
        )

        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum emails to send (1–500)",
        )

    def handle(self, *args, **options):

        batch_id = options["batch_id"]
        limit = options["limit"]

        if not 1 <= limit <= 500:
            self.stderr.write(
                self.style.ERROR(
                    "Limit must be between 1 and 500."
                )
            )
            return

        try:
            result = send_pending_activation_emails(
                batch_id=batch_id,
                limit=limit,
            )

        except StudentImportBatch.DoesNotExist:
            self.stderr.write(
                self.style.ERROR(
                    "Import batch does not exist."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Emails sent: {result.sent}"
            )
        )

        if result.failed:
            self.stderr.write(
                self.style.WARNING(
                    f"Failed deliveries: {result.failed}"
                )
            )