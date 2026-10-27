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
    return (
        user.is_authenticated
        and user.is_active
        and (
            user.is_superuser
            or has_role(user, UserProfile.Role.ADMIN)
        )
    )