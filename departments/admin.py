
from django.contrib import admin

from .models import Department, Program


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):

    list_display = (
        "code",
        "name",
        "is_active",
        "created_at",
    )

    list_filter = (
        "is_active",
    )

    search_fields = (
        "code",
        "name",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):

    list_display = (
        "code",
        "name",
        "department",
        "duration_semesters",
        "is_active",
    )

    list_filter = (
        "department",
        "is_active",
    )

    search_fields = (
        "code",
        "name",
        "department__name",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    list_select_related = (
        "department",
    )
