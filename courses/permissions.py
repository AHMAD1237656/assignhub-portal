
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from accounts.models import UserProfile


def has_role(user, role):
    return bool(
        user.is_authenticated
        and user.is_active
        and UserProfile.objects.filter(
            user=user,
            role=role,
        ).exists()
    )


def is_academic_admin(user):
    if not user.is_authenticated or not user.is_active:
        return False

    return bool(
        user.is_superuser
        or (
            user.is_staff
            and has_role(
                user,
                UserProfile.Role.ADMIN,
            )
        )
    )


def is_course_teacher(user):
    return has_role(
        user,
        UserProfile.Role.TEACHER,
    )


def academic_admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not is_academic_admin(request.user):
            raise PermissionDenied

        return view(request, *args, **kwargs)

    return wrapped


def teacher_or_admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not (
            is_academic_admin(request.user)
            or is_course_teacher(request.user)
        ):
            raise PermissionDenied

        return view(request, *args, **kwargs)

    return wrapped
