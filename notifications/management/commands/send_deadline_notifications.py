"""One-shot, idempotent deadline reminder command, suitable for hourly scheduling."""

from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db.models import Exists, OuterRef
from django.utils import timezone

from assignments.models import Assignment, Submission
from courses.models import CourseEnrollment
from notifications.models import Notification


class Command(BaseCommand):
    help = "Send in-app reminders to active enrolled students with deadlines in the next 24 hours."

    def handle(self, *args, **options):
        now = timezone.now()
        window = now + timedelta(hours=24)
        assignments = Assignment.objects.filter(
            status=Assignment.Status.PUBLISHED,
            deadline__gt=now,
            deadline__lte=window,
            course_offering__is_active=True,
            course_offering__course__is_active=True,
            course_offering__section__is_active=True,
        ).select_related("course_offering").order_by("deadline", "pk")

        count = 0
        for assignment in assignments.iterator(chunk_size=100):
            finalized = Submission.objects.filter(
                assignment_id=assignment.pk,
                student_id=OuterRef("student_id"),
                status__in=[Submission.Status.SUBMITTED, Submission.Status.GRADED],
            )
            enrollment_ids = (
                CourseEnrollment.objects.filter(
                    offering_id=assignment.course_offering_id,
                    status=CourseEnrollment.Status.ACTIVE,
                    student__is_active=True,
                )
                .annotate(done=Exists(finalized))
                .filter(done=False)
                .values_list("student_id", flat=True)
                .distinct()
            )
            # Re-check deadline/status just before notification generation.
            from notifications.services import _create
            from django.urls import reverse
            for student_id in enrollment_ids.iterator(chunk_size=300):
                event_key = f"deadline:24h:{assignment.pk}:{student_id}"
                if Notification.objects.filter(event_key=event_key).exists():
                    continue
                _create(
                    student_id,
                    Notification.Kind.DEADLINE,
                    "Assignment deadline approaching",
                    f"{assignment.title} is due within the next 24 hours.",
                    reverse("assignments:detail", args=[assignment.pk]),
                    event_key,
                )
                count += 1
        self.stdout.write(self.style.SUCCESS(f"Deadline reminder run completed; up to {count} new notifications."))
