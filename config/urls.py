from django.contrib import admin
from django.urls import include, path

from .views import home


urlpatterns = [
    path(
        "",
        home,
        name="home",
    ),

    path(
        "admin/",
        admin.site.urls,
    ),

    path(
        "accounts/",
        include("accounts.urls"),
    ),

    path(
        "assignments/",
        include("assignments.urls"),
    ),

    path(
        "courses/",
        include("courses.urls"),
    ),

    path(
        "semesters/",
        include("semesters.urls"),
    ),

    path(
        "departments/",
        include("departments.urls"),
    ),

]