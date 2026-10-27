
from django.contrib import admin

from .models import (
    Course,
    CourseEnrollment,
    CourseOffering,
)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "title",
        "program",
        "semester",
        "credit_hours",
        "is_active",
    )

    list_filter = (
        "program",
        "semester",
        "is_active",
    )

    search_fields = (
        "code",
        "title",
        "program__code",
    )

    list_select_related = (
        "program",
        "semester",
    )


@admin.register(CourseOffering)
class CourseOfferingAdmin(admin.ModelAdmin):
    list_display = (
        "course",
        "section",
        "teacher",
        "academic_year",
        "term",
        "is_active",
    )

    list_filter = (
        "academic_year",
        "term",
        "is_active",
    )

    search_fields = (
        "course__code",
        "course__title",
        "teacher__username",
    )

    list_select_related = (
        "course",
        "section",
        "teacher",
    )


@admin.register(CourseEnrollment)
class CourseEnrollmentAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "offering",
        "status",
        "enrolled_at",
    )

    list_filter = ("status",)

    search_fields = (
        "student__username",
        "offering__course__code",
    )

    list_select_related = (
        "student",
        "offering",
    )
