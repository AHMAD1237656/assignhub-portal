"""AssignHub: safe development activation-link preview + regression tests.

Run from repository root: python assignhub_activation_fix.py
"""

from pathlib import Path
from textwrap import dedent

ROOT = Path.cwd()


def update_file(relative_path, transform):
    path = ROOT / relative_path
    if not path.is_file():
        raise SystemExit(f"Missing file: {relative_path}. Run from project root.")
    original = path.read_text(encoding="utf-8")
    modified = transform(original)
    if modified == original:
        print(f"UNCHANGED: {relative_path}")
        return
    backup = path.with_name(path.name + ".before_activation_fix.bak")
    if not backup.exists():
        backup.write_text(original, encoding="utf-8")
    path.write_text(modified, encoding="utf-8")
    print(f"UPDATED: {relative_path} (backup: {backup.name})")


DETAIL_VIEW = dedent('''\
@login_required
def student_detail(request, identity_id):
    require_admin(request.user)

    identity = get_object_or_404(
        StudentIdentity.objects.select_related(
            "user",
            "section",
            "section__semester",
            "section__semester__program",
            "import_batch",
            "cancelled_by",
        ),
        pk=identity_id,
    )

    events = (
        identity.events
        .select_related("actor")
        .order_by("-created_at")[:30]
    )

    # Developer-only, admin-only activation link for THIS student.
    # Sign on the running web server with the latest stored nonce.
    # Never display activation tokens to ordinary students or in production.
    dev_activation_url = None
    if (
        settings.DEBUG
        and identity.status == StudentIdentity.Status.PENDING
        and not identity.user.is_active
        and not identity.user.has_usable_password()
    ):
        token = make_activation_token(identity)
        current_identity = get_identity_from_token(token)
        if current_identity is not None and current_identity.pk == identity.pk:
            dev_activation_url = (
                settings.ASSIGNHUB_PUBLIC_BASE_URL.rstrip("/")
                + reverse(
                    "student_onboarding:activate",
                    kwargs={"token": token},
                )
            )

    context = {
        "identity": identity,
        "edit_form": PendingStudentEditForm(identity=identity),
        "cancel_form": CancelPendingStudentForm(),
        "events": events,
        "dev_activation_url": dev_activation_url,
    }

    response = render(
        request,
        "student_onboarding/student_detail.html",
        context,
    )
    if dev_activation_url:
        response["Cache-Control"] = "private, no-store, max-age=0"
        response["Referrer-Policy"] = "no-referrer"
    return response
''')


def patch_admin_views(text):
    if "from django.conf import settings" not in text:
        anchor = "from django.contrib import messages\n"
        if anchor not in text:
            raise SystemExit("Unexpected admin_views imports; no changes made.")
        text = text.replace(anchor, "from django.conf import settings\n" + anchor, 1)
    if "from django.urls import reverse" not in text:
        anchor = "from django.views.decorators.http import require_POST\n"
        if anchor not in text:
            raise SystemExit("Unexpected admin_views imports; no changes made.")
        text = text.replace(anchor, "from django.urls import reverse\n" + anchor, 1)
    if "from .services import get_identity_from_token, make_activation_token" not in text:
        anchor = "from .models import StudentIdentity\n"
        if anchor not in text:
            raise SystemExit("Unexpected admin_views imports; no changes made.")
        text = text.replace(
            anchor,
            anchor + "from .services import get_identity_from_token, make_activation_token\n",
            1,
        )
    start_marker = "@login_required\ndef student_detail(request, identity_id):"
    end_marker = "\n\n@login_required\n@require_POST\ndef edit_student("
    if start_marker not in text or end_marker not in text:
        raise SystemExit("Student detail view markers not found; no changes made.")
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[:start] + DETAIL_VIEW.rstrip() + text[end:]


COPY_WIDGET = '''\
                    {% if dev_activation_url %}
                    <div class="border rounded-3 bg-light p-3 mt-3">
                        <div class="fw-semibold text-dark mb-2">
                            Development: Current Activation Link
                        </div>
                        <p class="small text-muted mb-2">
                            Link belongs only to {{ identity.user.get_full_name }}
                            ({{ identity.roll_number }}). Copy from here after
                            every resend. Visible to admins only in DEBUG mode.
                        </p>
                        <input
                            id="assignhub-current-activation-link"
                            type="text"
                            class="form-control form-control-sm mb-2"
                            value="{{ dev_activation_url }}"
                            readonly
                            autocomplete="off"
                            spellcheck="false"
                            aria-label="Current student activation URL"
                        >
                        <button
                            type="button"
                            class="btn btn-outline-primary btn-sm"
                            onclick="
                                const field = document.getElementById('assignhub-current-activation-link');
                                if (navigator.clipboard &amp;&amp; window.isSecureContext) {
                                    navigator.clipboard.writeText(field.value).then(() => {
                                        this.textContent = 'Copied!';
                                    }).catch(() => {
                                        field.focus(); field.select();
                                        this.textContent = 'Press Ctrl+C';
                                    });
                                } else {
                                    field.focus(); field.select();
                                    this.textContent = 'Press Ctrl+C';
                                }
                            "
                        >
                            Copy Current Link
                        </button>
                    </div>
                    {% endif %}
'''


def patch_student_template(text):
    if 'id="assignhub-current-activation-link"' in text:
        return text
    anchor = '''\
                    <div class="small text-muted mt-3">
                        Recipient:
                        {{ identity.institutional_email }}
                    </div>
'''
    if anchor not in text:
        raise SystemExit("Recipient block not found in student_detail.html.")
    return text.replace(anchor, anchor + "\n" + COPY_WIDGET, 1)


REGRESSION_TEST = '''\
    @override_settings(DEBUG=True)
    def test_two_students_have_independent_current_activation_links(self):
        self.provision_two_students()
        first = StudentIdentity.objects.get(roll_number="2026-SE-001")
        second = StudentIdentity.objects.get(roll_number="2026-SE-002")

        def current_url(identity):
            response = self.client.get(
                reverse("student_onboarding:student_detail", args=[identity.pk])
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Cache-Control"], "private, no-store, max-age=0")
            return response.context["dev_activation_url"]

        first_url = current_url(first)
        second_url = current_url(second)
        self.assertNotEqual(first_url, second_url)
        self.assertEqual(self.client.get(first_url).status_code, 200)
        self.assertEqual(self.client.get(second_url).status_code, 200)

        # Resending ONE student's email invalidates ONLY their old URL.
        response = self.client.post(
            reverse("student_onboarding:student_resend", args=[first.pk])
        )
        self.assertEqual(response.status_code, 302)
        emailed_first_token = mail.outbox[-1].body.split(
            "/student-onboarding/activate/", 1
        )[1].split("/", 1)[0]
        self.assertEqual(get_identity_from_token(emailed_first_token).pk, first.pk)
        self.assertEqual(self.client.get(first_url).status_code, 400)
        self.assertEqual(self.client.get(second_url).status_code, 200)
        first_url = current_url(first)
        self.assertEqual(self.client.get(first_url).status_code, 200)

        # A later resend for another student cannot invalidate the first.
        response = self.client.post(
            reverse("student_onboarding:student_resend", args=[second.pk])
        )
        self.assertEqual(response.status_code, 302)
        emailed_second_token = mail.outbox[-1].body.split(
            "/student-onboarding/activate/", 1
        )[1].split("/", 1)[0]
        self.assertEqual(get_identity_from_token(emailed_second_token).pk, second.pk)
        self.assertEqual(self.client.get(second_url).status_code, 400)
        self.assertEqual(self.client.get(first_url).status_code, 200)
        second_url = current_url(second)
        self.assertEqual(self.client.get(second_url).status_code, 200)

        # Activating first student does not affect second student's link.
        response = self.client.post(first_url, {
            "new_password1": "Strong#AcademicPass8642",
            "new_password2": "Strong#AcademicPass8642",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get(first_url).status_code, 400)
        self.assertEqual(self.client.get(second_url).status_code, 200)

    @override_settings(DEBUG=False)
    def test_activation_link_not_exposed_to_admin_in_production(self):
        self.provision_two_students()
        identity = StudentIdentity.objects.get(roll_number="2026-SE-001")
        response = self.client.get(
            reverse("student_onboarding:student_detail", args=[identity.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["dev_activation_url"])
        self.assertNotContains(response, "assignhub-current-activation-link")

'''


def patch_tests(text):
    if "def test_two_students_have_independent_current_activation_links" in text:
        return text
    anchor = "    def test_individual_activation_resend(self):"
    if anchor not in text:
        raise SystemExit("Test insertion marker not found in tests.py.")
    # Add methods inside the existing StudentOnboardingTests TestCase class.
    return text.replace(anchor, REGRESSION_TEST + anchor, 1)


def patch_settings(text):
    old = """SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = secrets.token_urlsafe(50)
    else:
        raise ImproperlyConfigured(
            "Set the DJANGO_SECRET_KEY environment variable when DEBUG is disabled."
        )"""
    new = """SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "Set a stable DJANGO_SECRET_KEY in .env before starting AssignHub."
    )"""
    if old not in text:
        if "stable DJANGO_SECRET_KEY" in text:
            return text
        raise SystemExit("Unexpected SECRET_KEY config. No changes made.")
    text = text.replace(old, new, 1)
    text = text.replace("import secrets\n", "", 1)
    return text


def patch_gitignore(text):
    additions = ["dev_emails/", "*.before_activation_fix.bak"]
    missing = [item for item in additions if item not in text.splitlines()]
    if not missing:
        return text
    return text.rstrip("\n") + "\n" + "\n".join(missing) + "\n"


def patch_services(text):
    start_marker = "def send_activation_email(*, body, recipient):"
    end_marker = "\n\ndef validate_section_capacity("
    if start_marker not in text or end_marker not in text:
        raise SystemExit("Email sender markers not found in services.py.")
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    replacement = dedent('''\
def send_activation_email(*, body, recipient):
    """Send a standards-compliant activation email.

    MIME transfer encodings in saved/console messages are decoded
    by email clients. Never copy encoded raw-MIME lines as URLs.
    """
    email = EmailMessage(
        subject="Activate your AssignHub student account",
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    return email.send(fail_silently=False)
''')
    return text[:start] + replacement.rstrip() + text[end:]


if __name__ == "__main__":
    required = [
        "student_onboarding/admin_views.py",
        "templates/student_onboarding/student_detail.html",
        "student_onboarding/tests.py",
        "config/settings.py",
        ".gitignore",
        "student_onboarding/services.py",
    ]
    for filename in required:
        if not (ROOT / filename).is_file():
            raise SystemExit(f"Not in AssignHub project root: {filename}")

    # Preflight all changes before touching files, to avoid partial edits.
    changes = [
        (required[0], patch_admin_views),
        (required[1], patch_student_template),
        (required[2], patch_tests),
        (required[3], patch_settings),
        (required[4], patch_gitignore),
        (required[5], patch_services),
    ]
    prepared = []
    for relative_path, transform in changes:
        path = ROOT / relative_path
        original = path.read_text(encoding="utf-8")
        modified = transform(original)
        compile(modified, relative_path, "exec") if relative_path.endswith(".py") else None
        prepared.append((path, original, modified))

    for path, original, modified in prepared:
        if original == modified:
            print(f"UNCHANGED: {path.relative_to(ROOT)}")
            continue
        backup = path.with_name(path.name + ".before_activation_fix.bak")
        if not backup.exists():
            backup.write_text(original, encoding="utf-8")
        path.write_text(modified, encoding="utf-8")
        print(f"UPDATED: {path.relative_to(ROOT)} (backup: {backup.name})")
    print("Done. Run: python manage.py check")
    print("Then: python manage.py test student_onboarding.tests --keepdb")
