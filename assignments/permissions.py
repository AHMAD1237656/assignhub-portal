
from accounts.models import UserProfile


def has_role(user, role):
    return (
        user.is_authenticated
        and user.is_active
        and UserProfile.objects.filter(
            user=user,
            role=role,
        ).exists()
    )


def is_teacher(user):
    return has_role(
        user,
        UserProfile.Role.TEACHER,
    )


def is_student(user):
    return has_role(
        user,
        UserProfile.Role.STUDENT,
    )


def is_admin(user):
    if not user.is_authenticated:
        return False

    if not user.is_active:
        return False

    if user.is_superuser:
        return True

    return (
        user.is_staff
        and has_role(
            user,
            UserProfile.Role.ADMIN,
        )
    )
