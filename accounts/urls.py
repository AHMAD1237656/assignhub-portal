from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.user_login, name="login"),
    path("logout/", views.user_logout, name="logout"),
    path("users/create/", views.user_create, name="user_create"),
]