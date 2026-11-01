"""Run as a separate process: python manage.py run_plagiarism_worker --backfill"""

import time

from django.core.management.base import BaseCommand

from assignments.auto_plagiarism import (
    process_next,
    queue_missing_reports,
    recover_stale_scans,
)


class Command(BaseCommand):
    help = "Process automatic plagiarism/OCR reports outside HTTP requests."

    def add_arguments(self, parser):
        parser.add_argument(
            "--backfill", action="store_true",
            help="Enqueue pre-existing finalized submissions (use once after install).",
        )
        parser.add_argument(
            "--drain", action="store_true",
            help="Process currently queued work, then exit.",
        )
        parser.add_argument("--poll", type=float, default=3.0)

    def handle(self, *args, **options):
        if options["backfill"]:
            count = queue_missing_reports()
            self.stdout.write(f"Queued {count} historical submission reports.")

        self.stdout.write("Plagiarism worker started. Ctrl+C to stop.")
        poll = max(0.5, min(float(options["poll"]), 60.0))
        try:
            while True:
                recover_stale_scans()
                if process_next():
                    continue
                if options["drain"]:
                    break
                time.sleep(poll)
        except KeyboardInterrupt:
            self.stdout.write("Plagiarism worker stopped.")
