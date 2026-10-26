# from django.urls import path

# from . import views


# app_name = "assignments"


# urlpatterns = [
#     path(
#         "",
#         views.assignment_list,
#         name="list",
#     ),

#     path(
#         "create/",
#         views.assignment_create,
#         name="create",
#     ),

#     path(
#         "<int:pk>/",
#         views.assignment_detail,
#         name="detail",
#     ),

#     path(
#         "<int:pk>/edit/",
#         views.assignment_edit,
#         name="edit",
#     ),

#     path(
#         "<int:pk>/delete/",
#         views.assignment_delete,
#         name="delete",
#     ),

#     path(
#         "<int:pk>/submit/",
#         views.submit_assignment,
#         name="submit",
#     ),

#     path(
#         "submissions/",
#         views.submission_list,
#         name="submissions",
#     ),

#     path(
#         "submissions/<int:pk>/review/",
#         views.submission_review,
#         name="submission_review",
#     ),
# ]
from django.urls import path

from . import views


app_name = "assignments"


urlpatterns = [
    path("", views.assignment_list, name="list"),
    path("create/", views.assignment_create, name="create"),
    path("submissions/", views.submission_list, name="submissions"),
    path(
        "submissions/<int:pk>/review/",
        views.submission_review,
        name="submission_review",
    ),
    path("<int:pk>/", views.assignment_detail, name="detail"),
    path("<int:pk>/edit/", views.assignment_edit, name="edit"),
    path("<int:pk>/delete/", views.assignment_delete, name="delete"),
    path("<int:pk>/submit/", views.submit_assignment, name="submit"),
]