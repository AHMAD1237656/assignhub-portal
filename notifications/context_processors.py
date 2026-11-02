from .models import Notification


def notification_context(request):
    """A small, recipient-filtered topbar preview; anonymous views make no queries."""
    user = request.user
    if not user.is_authenticated or not user.is_active:
        return {"ah_unread_count": 0, "ah_recent_notifications": ()}
    personal = Notification.objects.filter(recipient_id=user.pk, archived_at__isnull=True)
    return {
        "ah_unread_count": personal.filter(read_at__isnull=True).count(),
        "ah_recent_notifications": personal[:5],
    }
