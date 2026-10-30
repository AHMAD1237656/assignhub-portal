
from django.urls import path

from . import views
from . import admin_views


app_name = "student_onboarding"


urlpatterns = [

    # Existing onboarding workflow

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

    # Phase 8.1 - Student Management

    path(
        "students/",
        admin_views.student_directory,
        name="student_directory",
    ),

    path(
        "students/export/",
        admin_views.export_student_report,
        name="student_export",
    ),

    path(
        "students/<int:identity_id>/",
        admin_views.student_detail,
        name="student_detail",
    ),

    path(
        "students/<int:identity_id>/edit/",
        admin_views.edit_student,
        name="student_edit",
    ),

    path(
        "students/<int:identity_id>/cancel/",
        admin_views.cancel_student,
        name="student_cancel",
    ),

    path(
        "students/<int:identity_id>/restore/",
        admin_views.restore_student,
        name="student_restore",
    ),

    path(
        "students/<int:identity_id>/resend/",
        admin_views.resend_student_email,
        name="student_resend",
    ),

]
