from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.core.exceptions import PermissionDenied
from .models import UserProfile
from .forms import UserCreateForm
from django.views.decorators.http import require_POST
from django.db import IntegrityError
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

# ==========================================
# TEACHER MANAGEMENT
# ==========================================

from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods, require_POST

from accounts.forms import (
    TeacherCreateForm,
    TeacherUpdateForm,
)

TeacherUser = get_user_model()


def academic_admin_required(view_func):
    """
    Restrict teacher management to authorized administrators.
    """

    from functools import wraps

    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):

        is_admin = (
            request.user.is_superuser
            or (
                request.user.is_staff
                and UserProfile.objects.filter(
                    user=request.user,
                    role=UserProfile.Role.ADMIN,
                ).exists()
            )
        )

        if not is_admin:
            raise PermissionDenied(
                "Only administrators can manage teachers."
            )

        return view_func(
            request,
            *args,
            **kwargs,
        )

    return wrapper


def get_teacher_or_404(user_id):

    teacher_profile = get_object_or_404(
        UserProfile.objects.select_related("user"),
        user_id=user_id,
        role=UserProfile.Role.TEACHER,
    )

    return teacher_profile.user


# ------------------------------------------
# TEACHER DIRECTORY
# ------------------------------------------

@academic_admin_required
@require_http_methods(["GET"])
def teacher_directory(request):

    teachers = (
        UserProfile.objects
        .filter(
            role=UserProfile.Role.TEACHER
        )
        .select_related("user")
        .order_by(
            "user__first_name",
            "user__last_name",
            "user__username",
        )
    )

    search = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    if search:
        teachers = teachers.filter(
            Q(user__username__icontains=search)
            | Q(user__first_name__icontains=search)
            | Q(user__last_name__icontains=search)
            | Q(user__email__icontains=search)
        )

    if status == "active":
        teachers = teachers.filter(
            user__is_active=True
        )

    elif status == "inactive":
        teachers = teachers.filter(
            user__is_active=False
        )

    paginator = Paginator(
        teachers,
        15,
    )

    page_obj = paginator.get_page(
        request.GET.get("page")
    )

    context = {
        "teachers": page_obj,
        "page_obj": page_obj,
        "search_query": search,
        "selected_status": status,

        "total_teachers": UserProfile.objects.filter(
            role=UserProfile.Role.TEACHER
        ).count(),

        "active_teachers": UserProfile.objects.filter(
            role=UserProfile.Role.TEACHER,
            user__is_active=True,
        ).count(),

        "inactive_teachers": UserProfile.objects.filter(
            role=UserProfile.Role.TEACHER,
            user__is_active=False,
        ).count(),
    }

    return render(
        request,
        "accounts/teacher_directory.html",
        context,
    )


# ------------------------------------------
# CREATE TEACHER
# ------------------------------------------

@academic_admin_required
@require_http_methods(["GET", "POST"])
def teacher_create(request):

    if request.method == "POST":

        form = TeacherCreateForm(
            request.POST
        )

        if form.is_valid():

            try:
                with transaction.atomic():

                    teacher = form.save()

                    UserProfile.objects.create(
                        user=teacher,
                        role=UserProfile.Role.TEACHER,
                    )

            except IntegrityError:
                form.add_error(
                    None,
                    "Unable to create teacher account. "
                    "Please check the submitted information."
                )

            else:
                messages.success(
                    request,
                    "Teacher account created successfully.",
                )

                return redirect(
                    "accounts:teacher_directory"
                )

    else:
        form = TeacherCreateForm(
            initial={
                "is_active": True,
            }
        )

    return render(
        request,
        "accounts/teacher_create.html",
        {
            "form": form,
        },
    )


# ------------------------------------------
# EDIT TEACHER
# ------------------------------------------

@academic_admin_required
@require_http_methods(["GET", "POST"])
def teacher_edit(request, user_id):

    teacher = get_teacher_or_404(
        user_id
    )

    if request.method == "POST":

        form = TeacherUpdateForm(
            request.POST,
            instance=teacher,
        )

        if form.is_valid():

            form.save()

            messages.success(
                request,
                "Teacher information updated successfully.",
            )

            return redirect(
                "accounts:teacher_directory"
            )

    else:
        form = TeacherUpdateForm(
            instance=teacher,
        )

    return render(
        request,
        "accounts/teacher_edit.html",
        {
            "form": form,
            "teacher": teacher,
        },
    )


# ------------------------------------------
# ACTIVATE / DEACTIVATE TEACHER
# ------------------------------------------

@academic_admin_required
@require_POST
def teacher_toggle_status(request, user_id):

    with transaction.atomic():

        teacher = get_object_or_404(
            TeacherUser.objects.select_for_update(),
            pk=user_id,
            profile__role=UserProfile.Role.TEACHER,
        )

        teacher.is_active = not teacher.is_active

        teacher.save(
            update_fields=["is_active"]
        )

    if teacher.is_active:

        messages.success(
            request,
            "Teacher account activated successfully.",
        )

    else:

        messages.success(
            request,
            "Teacher account deactivated successfully.",
        )

    return redirect(
        "accounts:teacher_directory"
    )

