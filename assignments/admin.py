from django.contrib import admin

from .models import Assignment, Submission


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "created_by",
        "deadline",
        "total_marks",
        "status",
        "created_at",
    )

    list_filter = (
        "status",
        "deadline",
    )

    search_fields = (
        "title",
        "instructions",
        "created_by__username",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "assignment",
        "student",
        "status",
        "submitted_at",
        "marks",
    )

    list_filter = (
        "status",
        "submitted_at",
    )

    search_fields = (
        "assignment__title",
        "student__username",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
        "submitted_at",
    )