from django.urls import path

from . import views


app_name = "student_onboarding"


urlpatterns = [
    path(
        "",
        views.dashboard,
        name="dashboard",
    ),

    path(
        "upload/",
        views.upload_students,
        name="upload",
    ),

    path(
        "sample/",
        views.download_template,
        name="sample",
    ),

    path(
        "preview/<int:batch_id>/",
        views.preview_import,
        name="preview",
    ),

    path(
        "confirm/<int:batch_id>/",
        views.confirm_students,
        name="confirm",
    ),

    path(
        "batch/<int:batch_id>/",
        views.batch_detail,
        name="batch_detail",
    ),

    path(
        "batch/<int:batch_id>/send/",
        views.send_activation_emails,
        name="send",
    ),

    path(
        "activate/<str:token>/",
        views.activate_student,
        name="activate",
    ),
]