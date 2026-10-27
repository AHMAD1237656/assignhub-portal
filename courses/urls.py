
from django.urls import path
from . import views


app_name = "courses"


urlpatterns = [
    path(
        "",
        views.course_list,
        name="course_list",
    ),
    path(
        "create/",
        views.course_create,
        name="course_create",
    ),
    path(
        "<int:pk>/",
        views.course_detail,
        name="course_detail",
    ),
    path(
        "<int:pk>/edit/",
        views.course_edit,
        name="course_edit",
    ),
    path(
        "<int:pk>/toggle/",
        views.course_toggle,
        name="course_toggle",
    ),
    path(
        "<int:pk>/delete/",
        views.course_delete,
        name="course_delete",
    ),

    path(
        "offerings/",
        views.offering_list,
        name="offering_list",
    ),
    path(
        "offerings/create/",
        views.offering_create,
        name="offering_create",
    ),
    path(
        "offerings/<int:pk>/",
        views.offering_detail,
        name="offering_detail",
    ),
    path(
        "offerings/<int:pk>/edit/",
        views.offering_edit,
        name="offering_edit",
    ),
    path(
        "offerings/<int:pk>/toggle/",
        views.offering_toggle,
        name="offering_toggle",
    ),
    path(
        "offerings/<int:pk>/delete/",
        views.offering_delete,
        name="offering_delete",
    ),

    path(
        "enrollments/",
        views.enrollment_list,
        name="enrollment_list",
    ),
    path(
        "enrollments/create/",
        views.enrollment_create,
        name="enrollment_create",
    ),
    path(
        "enrollments/<int:pk>/edit/",
        views.enrollment_edit,
        name="enrollment_edit",
    ),
    path(
        "enrollments/<int:pk>/delete/",
        views.enrollment_delete,
        name="enrollment_delete",
    ),

    path(
        "api/sections/",
        views.sections_for_course_api,
        name="sections_for_course_api",
    ),
]
