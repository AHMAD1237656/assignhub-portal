from django.contrib import admin

from .models import StudentClassAllocation


@admin.register(StudentClassAllocation)
class StudentClassAllocationAdmin(
    admin.ModelAdmin
):

    list_display = (
        "student",
        "section",
        "academic_year",
        "term",
        "status",
        "assigned_by",
        "created_at",
        "ended_at",
    )

    list_filter = (
        "status",
        "academic_year",
        "term",
        "section",
    )

    search_fields = (
        "student__username",
        "student__first_name",
        "student__last_name",
        "section__code",
        "reason",
    )

    readonly_fields = (
        "student",
        "section",
        "academic_year",
        "term",
        "status",
        "assigned_by",
        "reason",
        "created_at",
        "ended_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(
        self,
        request,
        obj=None,
    ):
        return False

    def has_delete_permission(
        self,
        request,
        obj=None,
    ):
        return False

    def has_view_permission(
        self,
        request,
        obj=None,
    ):
        return (
            request.user.is_authenticated
            and request.user.is_active
            and request.user.is_superuser
        )