
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import SESSION_KEY, get_user_model
from django.contrib.auth.hashers import check_password
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .forms import UserCreateForm
from .models import UserProfile

User = get_user_model()

# Development convention: the current AssignHub uses Django's built-in User.
ADMIN_PASSWORD = "AdminStrongPass123!"
TEACHER_PASSWORD = "TeacherStrongPass123!"
STUDENT_PASSWORD = "StudentStrongPass123!"


@override_settings(
    MAILERS={"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}},
    PASSWORD_HASHERS=["django.contrib.auth.hashers.PBKDF2PasswordHasher"],
)
class AccountsTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="superadmin", email="superadmin@example.com", password=ADMIN_PASSWORD
        )
        cls.role_admin = User.objects.create_user(
            username="roleadmin", email="roleadmin@example.com",
            password=ADMIN_PASSWORD, is_staff=True
        )
        UserProfile.objects.create(user=cls.role_admin, role=UserProfile.Role.ADMIN)
        cls.teacher = User.objects.create_user(
            username="teacher", email="teacher@example.com",
            password=TEACHER_PASSWORD, is_staff=True
        )
        UserProfile.objects.create(user=cls.teacher, role=UserProfile.Role.TEACHER)
        cls.student = User.objects.create_user(
            username="student", email="student@example.com", password=STUDENT_PASSWORD
        )
        UserProfile.objects.create(user=cls.student, role=UserProfile.Role.STUDENT)
        cls.inactive = User.objects.create_user(
            username="inactive", email="inactive@example.com",
            password=STUDENT_PASSWORD, is_active=False
        )
        UserProfile.objects.create(user=cls.inactive, role=UserProfile.Role.STUDENT)

    @staticmethod
    def creation_data(**overrides):
        data = {
            "username": "newstudent", "first_name": "New", "last_name": "Student",
            "email": "newstudent@example.com", "password": "NewStrongPass123!",
            "role": UserProfile.Role.STUDENT, "is_active": "on",
        }
        data.update(overrides)
        return data

    def reset_link(self, user):
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        return reverse("accounts:password_reset_confirm", kwargs={"uidb64": uid, "token": token})


class RoutingAndPagesTests(AccountsTestBase):
    def test_login_page_renders(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/login.html")
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password"')

    def test_password_reset_page_renders(self):
        self.assertEqual(self.client.get(reverse("accounts:password_reset")).status_code, 200)

    def test_password_reset_done_page_renders(self):
        self.assertEqual(self.client.get(reverse("accounts:password_reset_done")).status_code, 200)

    def test_password_reset_complete_page_renders(self):
        self.assertEqual(self.client.get(reverse("accounts:password_reset_complete")).status_code, 200)

    def test_logged_out_user_redirected_from_create(self):
        url = reverse("accounts:user_create")
        response = self.client.get(url)
        self.assertRedirects(response, f"{settings.LOGIN_URL}?next={url}", fetch_redirect_response=False)

    def test_logged_in_user_create_page_renders(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("accounts:user_create"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/user_create.html")

    def test_authenticated_user_visiting_login_redirected(self):
        self.client.force_login(self.student)
        self.assertRedirects(self.client.get(reverse("accounts:login")), "/")

    def test_home_exists(self):
        self.assertEqual(self.client.get("/").status_code, 200)


class LoginTests(AccountsTestBase):
    def test_student_login(self):
        response = self.client.post(reverse("accounts:login"), {
            "username": "student", "password": STUDENT_PASSWORD,
        })
        self.assertRedirects(response, "/")
        self.assertEqual(int(self.client.session[SESSION_KEY]), self.student.pk)

    def test_admin_login(self):
        response = self.client.post(reverse("accounts:login"), {
            "username": "superadmin", "password": ADMIN_PASSWORD,
        })
        self.assertRedirects(response, "/")

    def test_teacher_login(self):
        response = self.client.post(reverse("accounts:login"), {
            "username": "teacher", "password": TEACHER_PASSWORD,
        })
        self.assertRedirects(response, "/")

    def test_wrong_password_stays_logged_out(self):
        response = self.client.post(reverse("accounts:login"), {
            "username": "student", "password": "not-the-password",
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_unknown_username_stays_logged_out(self):
        response = self.client.post(reverse("accounts:login"), {
            "username": "doesnotexist", "password": STUDENT_PASSWORD,
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_blank_credentials_rejected(self):
        response = self.client.post(reverse("accounts:login"), {"username": "", "password": ""})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_inactive_user_cannot_login(self):
        response = self.client.post(reverse("accounts:login"), {
            "username": "inactive", "password": STUDENT_PASSWORD,
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_login_failure_does_not_set_session(self):
        self.client.post(reverse("accounts:login"), {
            "username": "student", "password": "wrong",
        })
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_login_does_not_echo_password(self):
        response = self.client.post(reverse("accounts:login"), {
            "username": "student", "password": "UNIQUE-MUST-NOT-APPEAR-123",
        })
        self.assertNotContains(response, "UNIQUE-MUST-NOT-APPEAR-123")

    def test_deactivated_account_loses_access_on_next_request(self):
        self.client.force_login(self.student)
        self.student.is_active = False
        self.student.save(update_fields=["is_active"])
        response = self.client.get(reverse("accounts:user_create"))
        self.assertEqual(response.status_code, 302)
        # Django may retain the session identifier even when an inactive user
        # is treated as anonymous. Assert effective access is revoked instead.
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertTrue(response.url.startswith(reverse("accounts:login")))


class LogoutTests(AccountsTestBase):
    def test_logout_get_is_not_allowed(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.assertIn(SESSION_KEY, self.client.session)

    def test_logout_post_removes_session(self):
        self.client.force_login(self.student)
        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(response, reverse("accounts:login"))
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_logout_put_is_not_allowed(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.put(reverse("accounts:logout")).status_code, 405)

    def test_anonymous_logout_redirects_to_login(self):
        response = self.client.post(reverse("accounts:logout"))
        self.assertEqual(response.status_code, 302)


class AccountCreationPermissionTests(AccountsTestBase):
    def test_superuser_can_get_and_post(self):
        self.client.force_login(self.admin)
        url = reverse("accounts:user_create")
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, self.creation_data())
        self.assertRedirects(response, url)
        self.assertTrue(User.objects.filter(username="newstudent").exists())

    def test_staff_admin_role_can_get_and_post(self):
        self.client.force_login(self.role_admin)
        url = reverse("accounts:user_create")
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, self.creation_data()).status_code, 302)

    def test_staff_teacher_get_and_post_forbidden(self):
        self.client.force_login(self.teacher)
        url = reverse("accounts:user_create")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, self.creation_data()).status_code, 403)
        self.assertFalse(User.objects.filter(username="newstudent").exists())

    def test_student_get_and_post_forbidden(self):
        self.client.force_login(self.student)
        url = reverse("accounts:user_create")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, self.creation_data()).status_code, 403)
        self.assertFalse(User.objects.filter(username="newstudent").exists())

    def test_anonymous_post_cannot_create_user(self):
        response = self.client.post(reverse("accounts:user_create"), self.creation_data())
        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(username="newstudent").exists())

    def test_staff_without_profile_is_not_admin(self):
        staff = User.objects.create_user("staff_no_profile", password=TEACHER_PASSWORD, is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse("accounts:user_create")).status_code, 403)

    def test_nonstaff_with_admin_profile_is_not_admin(self):
        user = User.objects.create_user("admin_not_staff", password=STUDENT_PASSWORD)
        UserProfile.objects.create(user=user, role=UserProfile.Role.ADMIN)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("accounts:user_create")).status_code, 403)


class AccountCreationValidationTests(AccountsTestBase):
    def setUp(self):
        self.client.force_login(self.admin)

    def test_creation_saves_correct_role(self):
        self.client.post(reverse("accounts:user_create"), self.creation_data())
        user = User.objects.get(username="newstudent")
        self.assertEqual(user.profile.role, UserProfile.Role.STUDENT)
        self.assertTrue(user.is_active)

    def test_creation_hashes_password(self):
        self.client.post(reverse("accounts:user_create"), self.creation_data())
        user = User.objects.get(username="newstudent")
        self.assertNotEqual(user.password, "NewStrongPass123!")
        self.assertTrue(check_password("NewStrongPass123!", user.password))

    def test_creation_does_not_grant_staff_by_role(self):
        self.client.post(reverse("accounts:user_create"), self.creation_data(role=UserProfile.Role.TEACHER))
        user = User.objects.get(username="newstudent")
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)

    def test_creation_inactive_checkbox_unchecked(self):
        data = self.creation_data()
        data.pop("is_active")
        self.client.post(reverse("accounts:user_create"), data)
        user = User.objects.get(username="newstudent")
        self.assertFalse(user.is_active)

    def test_duplicate_username_rejected(self):
        response = self.client.post(reverse("accounts:user_create"), self.creation_data(username="student"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.filter(username="student").count(), 1)

    def test_empty_username_rejected(self):
        response = self.client.post(reverse("accounts:user_create"), self.creation_data(username=""))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="newstudent@example.com").exists())

    def test_invalid_email_rejected(self):
        response = self.client.post(reverse("accounts:user_create"), self.creation_data(email="not-an-email"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="newstudent").exists())

    def test_missing_password_rejected(self):
        response = self.client.post(reverse("accounts:user_create"), self.creation_data(password=""))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="newstudent").exists())

    def test_weak_common_password_rejected(self):
        response = self.client.post(reverse("accounts:user_create"), self.creation_data(password="password"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="newstudent").exists())

    def test_numeric_password_rejected(self):
        response = self.client.post(reverse("accounts:user_create"), self.creation_data(password="1234567890123456"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="newstudent").exists())

    def test_invalid_role_rejected(self):
        response = self.client.post(reverse("accounts:user_create"), self.creation_data(role="SUPERROOT"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="newstudent").exists())

    def test_html_special_characters_not_executed_in_error(self):
        payload = '<script>alert("xss")</script>'
        response = self.client.post(reverse("accounts:user_create"), self.creation_data(username=payload))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, payload, html=False)

    def test_form_rejects_password_similar_to_username(self):
        form = UserCreateForm(data=self.creation_data(username="newstudent123", password="newstudent123"))
        self.assertFalse(form.is_valid())
        self.assertIn("password", form.errors)


class ProfileIntegrityTests(AccountsTestBase):
    def test_role_values_available(self):
        self.assertEqual(set(UserProfile.Role.values), {"ADMIN", "TEACHER", "STUDENT"})

    def test_profile_matches_user(self):
        self.assertEqual(self.student.profile.user_id, self.student.pk)
        self.assertEqual(self.student.profile.role, UserProfile.Role.STUDENT)

    def test_second_profile_for_same_user_blocked(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserProfile.objects.create(user=self.student, role=UserProfile.Role.TEACHER)

    def test_deleting_user_deletes_profile(self):
        user_id = self.student.pk
        self.student.delete()
        self.assertFalse(UserProfile.objects.filter(user_id=user_id).exists())


class PasswordResetTests(AccountsTestBase):
    def test_reset_sends_email_to_active_registered_user(self):
        response = self.client.post(reverse("accounts:password_reset"), {"email": "student@example.com"})
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/accounts/reset/", mail.outbox[0].body)

    def test_unknown_email_same_public_response(self):
        response = self.client.post(reverse("accounts:password_reset"), {"email": "nobody@example.com"})
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_inactive_user_not_sent_reset_email(self):
        self.client.post(reverse("accounts:password_reset"), {"email": "inactive@example.com"})
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_email_has_form_error(self):
        response = self.client.post(reverse("accounts:password_reset"), {"email": "invalid-email"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter a valid email")

    def test_valid_reset_token_shows_form(self):
        response = self.client.get(self.reset_link(self.student), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="new_password1"')

    def test_invalid_token_rejected(self):
        uid = urlsafe_base64_encode(force_bytes(self.student.pk))
        url = reverse("accounts:password_reset_confirm", kwargs={"uidb64": uid, "token": "bad-token"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "invalid or expired")

    def test_malformed_uid_rejected_without_500(self):
        url = reverse("accounts:password_reset_confirm", kwargs={"uidb64": "notvalid", "token": "bad-token"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_password_reset_updates_password_and_invalidates_old_one(self):
        first = self.client.get(self.reset_link(self.student))
        self.assertEqual(first.status_code, 302)
        url = first["Location"]
        response = self.client.post(url, {
            "new_password1": "ChangedStrongPass123!",
            "new_password2": "ChangedStrongPass123!",
        })
        self.assertRedirects(response, reverse("accounts:password_reset_complete"))
        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password("ChangedStrongPass123!"))
        self.assertFalse(self.student.check_password(STUDENT_PASSWORD))

    def test_mismatched_new_passwords_rejected(self):
        first = self.client.get(self.reset_link(self.student))
        response = self.client.post(first["Location"], {
            "new_password1": "ChangedStrongPass123!",
            "new_password2": "DifferentStrongPass456!",
        })
        self.assertEqual(response.status_code, 200)
        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password(STUDENT_PASSWORD))

    def test_weak_reset_password_rejected(self):
        first = self.client.get(self.reset_link(self.student))
        response = self.client.post(first["Location"], {
            "new_password1": "password", "new_password2": "password",
        })
        self.assertEqual(response.status_code, 200)
        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password(STUDENT_PASSWORD))

    def test_token_invalid_after_password_changed(self):
        url = self.reset_link(self.student)
        self.student.set_password("ChangedStrongPass123!")
        self.student.save()
        response = self.client.get(url)
        self.assertContains(response, "invalid or expired")

    @override_settings(PASSWORD_RESET_TIMEOUT=1)
    def test_expired_reset_token_rejected(self):
        from django.contrib.auth.tokens import PasswordResetTokenGenerator
        generator = PasswordResetTokenGenerator()
        # Token issued three seconds in the past (Django internal timestamp in seconds).
        with patch.object(generator, "_now", return_value=timezone.now().replace(tzinfo=None) - timedelta(seconds=3)):
            token = generator.make_token(self.student)
        uid = urlsafe_base64_encode(force_bytes(self.student.pk))
        url = reverse("accounts:password_reset_confirm", kwargs={"uidb64": uid, "token": token})
        self.assertContains(self.client.get(url), "invalid or expired")


class CSRFSecurityTests(AccountsTestBase):
    def setUp(self):
        self.secure_client = Client(enforce_csrf_checks=True)

    def test_login_post_without_csrf_rejected(self):
        response = self.secure_client.post(reverse("accounts:login"), {
            "username": "student", "password": STUDENT_PASSWORD,
        })
        self.assertEqual(response.status_code, 403)

    def test_user_creation_post_without_csrf_rejected(self):
        self.secure_client.force_login(self.admin)
        response = self.secure_client.post(reverse("accounts:user_create"), self.creation_data())
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="newstudent").exists())

    def test_logout_post_without_csrf_rejected_and_session_preserved(self):
        self.secure_client.force_login(self.student)
        response = self.secure_client.post(reverse("accounts:logout"))
        self.assertEqual(response.status_code, 403)
        self.assertIn(SESSION_KEY, self.secure_client.session)

    def test_reset_request_without_csrf_rejected(self):
        response = self.secure_client.post(reverse("accounts:password_reset"), {
            "email": "student@example.com"
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)

    def test_login_with_valid_csrf_succeeds(self):
        self.secure_client.get(reverse("accounts:login"))
        token = self.secure_client.cookies[settings.CSRF_COOKIE_NAME].value
        response = self.secure_client.post(reverse("accounts:login"), {
            "username": "student", "password": STUDENT_PASSWORD, "csrfmiddlewaretoken": token,
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn(SESSION_KEY, self.secure_client.session)


class BrowserSecurityTests(AccountsTestBase):
    def test_login_does_not_redirect_to_external_next_parameter(self):
        response = self.client.post(reverse("accounts:login") + "?next=https://attacker.example/", {
            "username": "student", "password": STUDENT_PASSWORD,
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(response["Location"].startswith("https://attacker.example"))

    def test_anonymous_cannot_create_user_using_post(self):
        before = User.objects.count()
        self.client.post(reverse("accounts:user_create"), self.creation_data())
        self.assertEqual(User.objects.count(), before)

    def test_student_cannot_create_admin_via_post(self):
        self.client.force_login(self.student)
        before = User.objects.count()
        self.client.post(reverse("accounts:user_create"), self.creation_data(role=UserProfile.Role.ADMIN))
        self.assertEqual(User.objects.count(), before)

    def test_teacher_cannot_create_admin_via_post(self):
        self.client.force_login(self.teacher)
        before = User.objects.count()
        self.client.post(reverse("accounts:user_create"), self.creation_data(role=UserProfile.Role.ADMIN))
        self.assertEqual(User.objects.count(), before)

    def test_role_cannot_be_elevated_by_unexpected_post_fields(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("accounts:user_create"), self.creation_data(
            is_staff="on", is_superuser="on", groups="1"
        ))
        user = User.objects.get(username="newstudent")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_sql_metacharacters_cannot_authenticate(self):
        response = self.client.post(reverse("accounts:login"), {
            "username": "' OR 1=1 --", "password": "' OR 1=1 --",
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SESSION_KEY, self.client.session)
