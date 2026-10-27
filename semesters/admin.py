
from django.contrib import admin

from .models import Section, Semester


@admin.register(Semester)
class SemesterAdmin(admin.ModelAdmin):
    list_display = (
        "program",
        "number",
        "is_active",
        "created_at",
    )

    list_filter = (
        "program",
        "is_active",
    )

    search_fields = (
        "program__code",
        "program__name",
    )

    list_select_related = (
        "program",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "semester",
        "capacity",
        "is_active",
    )

    list_filter = (
        "semester__program",
        "semester",
        "is_active",
    )

    search_fields = (
        "code",
        "semester__program__code",
    )

    list_select_related = (
        "semester",
        "semester__program",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )
