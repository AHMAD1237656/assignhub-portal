
from accounts.models import UserProfile


def assignhub_navigation(request):
    user = request.user

    defaults = {
        "nav_is_admin": False,
        "nav_is_teacher": False,
        "nav_is_student": False,
    }

    if not user.is_authenticated or not user.is_active:
        return defaults

    if user.is_superuser:
        defaults["nav_is_admin"] = True
        return defaults

    role = (
        UserProfile.objects.filter(
            user_id=user.pk
        )
        .values_list("role", flat=True)
        .first()
    )

    defaults["nav_is_admin"] = (
        user.is_staff
        and role == UserProfile.Role.ADMIN
    )

    defaults["nav_is_teacher"] = (
        role == UserProfile.Role.TEACHER
    )

    defaults["nav_is_student"] = (
        role == UserProfile.Role.STUDENT
    )

    return defaults
