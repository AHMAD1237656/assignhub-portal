from django.contrib import admin
from .models import MonitoringEvent, MonitoringSession, ProctoringPolicy


@admin.register(ProctoringPolicy)
class ProctoringPolicyAdmin(admin.ModelAdmin):
    list_display = ('quiz', 'enabled', 'require_camera', 'log_browser_events')
    readonly_fields = ('quiz', 'enabled', 'require_camera', 'log_browser_events', 'updated_at')
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MonitoringSession)
class MonitoringSessionAdmin(admin.ModelAdmin):
    list_display = ('attempt', 'consent_at', 'last_heartbeat_at', 'closed_at')
    readonly_fields = ('attempt', 'consent_at', 'camera_check_claimed', 'started_at', 'last_heartbeat_at', 'closed_at')
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MonitoringEvent)
class MonitoringEventAdmin(admin.ModelAdmin):
    list_display = ('session', 'kind', 'review_status', 'created_at')
    readonly_fields = ('session', 'kind', 'review_status', 'created_at', 'reviewed_at', 'reviewed_by')
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
