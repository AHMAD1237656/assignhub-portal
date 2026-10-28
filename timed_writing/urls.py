from django.urls import path

from . import views


app_name = "timed_writing"


urlpatterns = [
    path(
        "<int:assignment_pk>/configure/",
        views.configure,
        name="configure",
    ),

    path(
        "<int:assignment_pk>/",
        views.editor,
        name="editor",
    ),

    path(
        "<int:assignment_pk>/start/",
        views.start,
        name="start",
    ),

    path(
        "<int:assignment_pk>/status/",
        views.status,
        name="status",
    ),

    path(
        "<int:assignment_pk>/save/",
        views.save,
        name="save",
    ),
]