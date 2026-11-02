from django.contrib import admin
from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "kind", "title", "created_at", "read_at")
    list_filter = ("kind", "created_at", "read_at")
    search_fields = ("recipient__username", "title", "event_key")
    readonly_fields = (
        "recipient", "kind", "title", "message", "target_url",
        "event_key", "read_at", "archived_at", "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
