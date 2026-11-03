from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from quiz_proctoring.models import MonitoringEvent


class Command(BaseCommand):
    help = 'Delete browser-monitoring event records older than 30 days (default).'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30)

    def handle(self, *args, **options):
        days = max(1, options['days'])
        cutoff = timezone.now() - timedelta(days=days)
        total, _ = MonitoringEvent.objects.filter(created_at__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(f'Deleted {total} old event row(s).'))
