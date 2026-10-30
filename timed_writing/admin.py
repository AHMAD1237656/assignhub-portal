from django.contrib import admin

from .models import (
    TimedWritingAttempt,
    TimedWritingConfig,
)


@admin.register(TimedWritingConfig)
class TimedWritingConfigAdmin(admin.ModelAdmin):

    list_display = (
        "assignment",
        "duration_minutes",
        "is_enabled",
        "created_at",
    )

    search_fields = (
        "assignment__title",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TimedWritingAttempt)
class TimedWritingAttemptAdmin(admin.ModelAdmin):

    list_display = (
        "config",
        "student",
        "status",
        "started_at",
        "expires_at",
        "revision",
        "auto_submitted",
    )

    search_fields = (
        "student__username",
        "config__assignment__title",
    )

    list_filter = (
        "status",
        "auto_submitted",
    )

    readonly_fields = (
        "config",
        "student",
        "submission",
        "started_at",
        "expires_at",
        "status",
        "revision",
        "auto_submitted",
        "finalized_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False