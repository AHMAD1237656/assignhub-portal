from django.urls import path

from . import views


app_name = "class_allocations"


urlpatterns = [
    path(
        "",
        views.dashboard,
        name="dashboard",
    ),

    path(
        "allocate/",
        views.allocate,
        name="allocate",
    ),

    path(
        "sync/",
        views.sync_enrollments,
        name="sync",
    ),

    path(
        "my-classes/",
        views.my_classes,
        name="my_classes",
    ),

    path(
        "my-classes/<int:offering_id>/",
        views.class_roster,
        name="class_roster",
    ),
]