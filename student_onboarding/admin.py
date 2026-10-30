from django.contrib import admin

from .models import (
    StudentIdentity,
    StudentImportBatch,
)


class ReadOnlyImportAdmin:
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StudentImportBatch)
class StudentImportBatchAdmin(
    ReadOnlyImportAdmin,
    admin.ModelAdmin,
):
    list_display = (
        "id",
        "filename",
        "section",
        "academic_year",
        "term",
        "status",
        "created_count",
        "created_by",
        "created_at",
    )

    list_filter = (
        "status",
        "academic_year",
        "term",
    )

    search_fields = (
        "filename",
        "section__code",
    )

    readonly_fields = (
        "filename",
        "section",
        "academic_year",
        "term",
        "status",
        "rows",
        "row_count",
        "created_count",
        "created_by",
        "created_at",
        "confirmed_at",
    )


@admin.register(StudentIdentity)
class StudentIdentityAdmin(
    ReadOnlyImportAdmin,
    admin.ModelAdmin,
):
    list_display = (
        "roll_number",
        "user",
        "institutional_email",
        "section",
        "status",
        "email_status",
        "activated_at",
    )

    list_filter = (
        "status",
        "email_status",
        "academic_year",
        "term",
    )

    search_fields = (
        "roll_number",
        "institutional_email",
        "user__username",
    )

    readonly_fields = (
        "user",
        "import_batch",
        "roll_number",
        "institutional_email",
        "section",
        "academic_year",
        "term",
        "status",
        "activation_nonce",
        "email_status",
        "email_claimed_at",
        "email_sent_at",
        "activated_at",
        "created_at",
    )