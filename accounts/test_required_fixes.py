"""Targeted tests for Account/Admin permission consistency."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.forms import UserCreateForm
from accounts.models import UserProfile
from config.views import get_dashboard_role


class RequiredHardeningAccountTests(TestCase):
    def test_new_role_admin_is_staff_and_not_superuser(self):
        form = UserCreateForm(data={
            "username": "patch_role_admin",
            "first_name": "Admin", "last_name": "Tester",
            "email": "patch_admin@example.com",
            "password": "NewAdminPass123!", "role": UserProfile.Role.ADMIN,
            "is_active": True,
        })
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(get_dashboard_role(user), "admin")

    def test_new_teacher_is_not_staff(self):
        form = UserCreateForm(data={
            "username": "patch_teacher", "first_name": "Teacher",
            "last_name": "Tester", "email": "patch_teacher@example.com",
            "password": "NewTeacherPass123!", "role": UserProfile.Role.TEACHER,
            "is_active": True,
        })
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertFalse(user.is_staff)
        self.assertEqual(get_dashboard_role(user), "teacher")

    def test_nonstaff_role_admin_does_not_get_admin_dashboard(self):
        user = get_user_model().objects.create_user(
            username="legacy_unprivileged_admin", password="ValidPass123!"
        )
        UserProfile.objects.create(user=user, role=UserProfile.Role.ADMIN)
        self.assertEqual(get_dashboard_role(user), "unknown")
