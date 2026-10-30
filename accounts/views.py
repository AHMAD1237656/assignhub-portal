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

# ==========================================
# PHASE 9.1 - PROFILE MANAGEMENT
# ==========================================

from django.apps import apps
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import render, redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters

from accounts.models import UserProfile
from accounts.forms import SelfProfileUpdateForm


def build_my_profile_context(user, mode, form=None):
    """
    Reuse existing base.html for profile pages.
    No additional HTML template is required.
    """

    role_profile = (
        UserProfile.objects
        .filter(user=user)
        .first()
    )

    student_identity = None

    if apps.is_installed("student_onboarding"):

        StudentIdentity = apps.get_model(
            "student_onboarding",
            "StudentIdentity",
        )

        student_identity = (
            StudentIdentity.objects
            .select_related("section")
            .filter(user=user)
            .first()
        )

    is_student = (
        role_profile is not None
        and role_profile.role == UserProfile.Role.STUDENT
    )

    email_locked = (
        is_student or student_identity is not None
    )

    return {
        "assignhub_profile_page": mode,
        "profile_role": role_profile,
        "student_identity": student_identity,
        "profile_email_locked": email_locked,
        "profile_form": form,
    }


@login_required
@never_cache
def my_profile(request):

    context = build_my_profile_context(
        request.user,
        mode="view",
    )

    return render(
        request,
        "base.html",
        context,
    )


@login_required
@never_cache
def edit_my_profile(request):

    context = build_my_profile_context(
        request.user,
        mode="edit",
    )

    email_locked = context["profile_email_locked"]

    if request.method == "POST":

        form = SelfProfileUpdateForm(
            request.POST,
            instance=request.user,
            email_locked=email_locked,
        )

        if form.is_valid():

            form.save()

            messages.success(
                request,
                "Your profile has been updated successfully.",
            )

            return redirect(
                "accounts:my_profile"
            )

    else:

        form = SelfProfileUpdateForm(
            instance=request.user,
            email_locked=email_locked,
        )

    context["profile_form"] = form

    return render(
        request,
        "base.html",
        context,
    )


@login_required
@sensitive_post_parameters()
@never_cache
def my_profile_password(request):

    if request.method == "POST":

        form = PasswordChangeForm(
            user=request.user,
            data=request.POST,
        )

        if form.is_valid():

            updated_user = form.save()

            # Keep the current session authenticated
            # after the password is changed.
            update_session_auth_hash(
                request,
                updated_user,
            )

            messages.success(
                request,
                "Your password has been changed successfully.",
            )

            return redirect(
                "accounts:my_profile"
            )

    else:

        form = PasswordChangeForm(
            user=request.user,
        )

    # Apply the existing Bootstrap styling
    # without requiring an extra form file.
    for field in form.fields.values():
        field.widget.attrs.update({
            "class": "form-control",
        })

    form.fields["old_password"].widget.attrs[
        "autocomplete"
    ] = "current-password"

    form.fields["new_password1"].widget.attrs[
        "autocomplete"
    ] = "new-password"

    form.fields["new_password2"].widget.attrs[
        "autocomplete"
    ] = "new-password"

    context = build_my_profile_context(
        request.user,
        mode="password",
        form=form,
    )

    return render(
        request,
        "base.html",
        context,
    )
