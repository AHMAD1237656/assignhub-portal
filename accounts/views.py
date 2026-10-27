from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.core.exceptions import PermissionDenied
from .models import UserProfile
from .forms import UserCreateForm
from django.views.decorators.http import require_POST

def user_login(request):
    if request.user.is_authenticated:
        return redirect("/")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        user = authenticate(
            request,
            username=username,
            password=password,
        )

        if user is not None:
            if user.is_active:
                login(request, user)
                return redirect("/")
            else:
                messages.error(
                    request,
                    "Your account is inactive.",
                )
        else:
            messages.error(
                request,
                "Invalid username or password.",
            )

    return render(
        request,
        "accounts/login.html",
    )


@login_required
@require_POST
def user_logout(request):
    logout(request)

    messages.success(
        request,
        "You have been logged out successfully."
    )

    return redirect("accounts:login")

@login_required
def user_create(request):
    if not (
        request.user.is_superuser
        or (
            request.user.is_staff
            and UserProfile.objects.filter(
                user=request.user,
                role=UserProfile.Role.ADMIN,
            ).exists()
        )
    ):
        raise PermissionDenied(
            "Only administrators can create users."
        )
    if request.method == "POST":
        form = UserCreateForm(request.POST)

        if form.is_valid():
            form.save()

            messages.success(
                request,
                "User account created successfully.",
            )

            return redirect("accounts:user_create")

    else:
        form = UserCreateForm()

    return render(
        request,
        "accounts/user_create.html",
        {"form": form},
    )