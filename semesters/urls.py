
from django.urls import path
from . import views


app_name = "semesters"


urlpatterns = [
    # Semesters
    path(
        "",
        views.semester_list,
        name="semester_list",
    ),
    path(
        "create/",
        views.semester_create,
        name="semester_create",
    ),
    path(
        "<int:pk>/",
        views.semester_detail,
        name="semester_detail",
    ),
    path(
        "<int:pk>/edit/",
        views.semester_edit,
        name="semester_edit",
    ),
    path(
        "<int:pk>/toggle/",
        views.semester_toggle,
        name="semester_toggle",
    ),
    path(
        "<int:pk>/delete/",
        views.semester_delete,
        name="semester_delete",
    ),

    # Sections
    path(
        "sections/",
        views.section_list,
        name="section_list",
    ),
    path(
        "sections/create/",
        views.section_create,
        name="section_create",
    ),
    path(
        "sections/<int:pk>/",
        views.section_detail,
        name="section_detail",
    ),
    path(
        "sections/<int:pk>/edit/",
        views.section_edit,
        name="section_edit",
    ),
    path(
        "sections/<int:pk>/toggle/",
        views.section_toggle,
        name="section_toggle",
    ),
    path(
        "sections/<int:pk>/delete/",
        views.section_delete,
        name="section_delete",
    ),

    # JSON APIs for dependent dropdowns
    path(
        "api/semesters/",
        views.semester_options_api,
        name="semester_options_api",
    ),
    path(
        "api/sections/",
        views.section_options_api,
        name="section_options_api",
    ),
]
