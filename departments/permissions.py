
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from accounts.models import UserProfile


def is_academic_admin(user):
    if not user.is_authenticated:
        return False

    if not user.is_active:
        return False

    if user.is_superuser:
        return True

    return (
        user.is_staff
        and UserProfile.objects.filter(
            user=user,
            role=UserProfile.Role.ADMIN,
        ).exists()
    )


def academic_admin_required(view_func):

    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):

        if not is_academic_admin(request.user):
            raise PermissionDenied(
                "Only administrators can manage "
                "departments and programs."
            )

        return view_func(
            request,
            *args,
            **kwargs,
        )

    return wrapper
