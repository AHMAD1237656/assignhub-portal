from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from notifications.models import Notification


class Command(BaseCommand):
    help = "Archive read notifications older than the configured age (default 90 days)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=90)

    def handle(self, *args, **options):
        days = max(1, options["days"])
        n = Notification.objects.filter(
    archived_at__isnull=True,
    read_at__isnull=False,
    created_at__lt=timezone.now() - timedelta(days=days),
).update(archived_at=timezone.now())
