
from django.urls import path

from . import views


app_name = "departments"


urlpatterns = [

    # Department routes
    path(
        "",
        views.department_list,
        name="department_list",
    ),

    path(
        "create/",
        views.department_create,
        name="department_create",
    ),

    path(
        "<int:pk>/",
        views.department_detail,
        name="department_detail",
    ),

    path(
        "<int:pk>/edit/",
        views.department_edit,
        name="department_edit",
    ),

    path(
        "<int:pk>/toggle/",
        views.department_toggle,
        name="department_toggle",
    ),

    path(
        "<int:pk>/delete/",
        views.department_delete,
        name="department_delete",
    ),

    # Program routes
    path(
        "programs/",
        views.program_list,
        name="program_list",
    ),

    path(
        "programs/create/",
        views.program_create,
        name="program_create",
    ),

    path(
        "programs/<int:pk>/",
        views.program_detail,
        name="program_detail",
    ),

    path(
        "programs/<int:pk>/edit/",
        views.program_edit,
        name="program_edit",
    ),

    path(
        "programs/<int:pk>/toggle/",
        views.program_toggle,
        name="program_toggle",
    ),

    path(
        "programs/<int:pk>/delete/",
        views.program_delete,
        name="program_delete",
    ),
]
