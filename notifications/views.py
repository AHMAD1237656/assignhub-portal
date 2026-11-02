from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .models import Notification


def _personal(request):
    return Notification.objects.filter(recipient_id=request.user.pk, archived_at__isnull=True)


@login_required
@never_cache
@require_GET
def notification_list(request):
    scope = request.GET.get("filter", "all")
    if scope not in {"all", "unread", "read"}:
        scope = "all"
    base = _personal(request)
    displayed = base
    if scope == "unread":
        displayed = displayed.filter(read_at__isnull=True)
    elif scope == "read":
        displayed = displayed.filter(read_at__isnull=False)

    pager = Paginator(displayed, 15)
    page_obj = pager.get_page(request.GET.get("page"))
    return render(request, "notifications/list.html", {
        "page_obj": page_obj,
        "scope": scope,
        "total_count": base.count(),
        "unread_count": base.filter(read_at__isnull=True).count(),
        "read_count": base.filter(read_at__isnull=False).count(),
    })


@login_required
@never_cache
@require_GET
def notification_count(request):
    # Useful for the topbar; no user IDs or message contents exposed.
    return JsonResponse({
        "unread_count": _personal(request).filter(read_at__isnull=True).count(),
    })


@login_required
@require_POST
def mark_read(request, pk):
    notice = get_object_or_404(_personal(request), pk=pk)
    if notice.read_at is None:
        _personal(request).filter(pk=notice.pk, read_at__isnull=True).update(
            read_at=timezone.now()
        )
    return redirect("notifications:list")


@login_required
@require_POST
def open_notification(request, pk):
    notice = get_object_or_404(_personal(request), pk=pk)
    if notice.read_at is None:
        _personal(request).filter(pk=notice.pk, read_at__isnull=True).update(
            read_at=timezone.now()
        )
    destination = notice.target_url
    # Open-redirect protection even if a row is modified via the database.
    if destination.startswith("/") and not destination.startswith("//") and "\\" not in destination:
        return redirect(destination)
    return redirect("notifications:list")


@login_required
@require_POST
def mark_all_read(request):
    _personal(request).filter(read_at__isnull=True).update(read_at=timezone.now())
    messages.success(request, "All notifications marked as read.")
    return redirect("notifications:list")


@login_required
@require_POST
def clear_read(request):
    hidden = _personal(request).filter(read_at__isnull=False).update(archived_at=timezone.now())
    messages.success(request, f"Archived {hidden} read notification(s).")
    return redirect("notifications:list")
