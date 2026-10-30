import csv
import secrets

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.core.exceptions import (
    PermissionDenied,
    ValidationError,
)
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from accounts.models import UserProfile
from class_allocations.services import allocate_students

from .forms import StudentImportForm
from .import_utils import parse_students_file
from .models import (
    StudentIdentity,
    StudentImportBatch,
)
from .services import (
    confirm_import,
    get_identity_from_token,
    send_pending_activation_emails,
)


User = get_user_model()


def require_admin(user):
    authorized = (
        user.is_authenticated
        and user.is_active
        and (
            user.is_superuser
            or (
                user.is_staff
                and UserProfile.objects.filter(
                    user=user,
                    role=UserProfile.Role.ADMIN,
                ).exists()
            )
        )
    )

    if not authorized:
        raise PermissionDenied(
            "Only administrators can manage student imports."
        )


@login_required
def dashboard(request):
    require_admin(request.user)

    batches = (
        StudentImportBatch.objects
        .select_related(
            "created_by",
            "section",
            "section__semester",
            "section__semester__program",
        )
        .order_by("-created_at")[:30]
    )

    context = {
        "batches": batches,
        "total_students": StudentIdentity.objects.count(),
        "pending_students": StudentIdentity.objects.filter(
            status=StudentIdentity.Status.PENDING
        ).count(),
        "activated_students": StudentIdentity.objects.filter(
            status=StudentIdentity.Status.ACTIVE
        ).count(),
    }

    return render(
        request,
        "student_onboarding/dashboard.html",
        context,
    )


@login_required
def upload_students(request):
    require_admin(request.user)

    if request.method == "POST":
        form = StudentImportForm(
            request.POST,
            request.FILES,
        )

        if form.is_valid():
            try:
                rows = parse_students_file(
                    form.cleaned_data["file"]
                )
            except ValidationError as exc:
                for error in exc.messages:
                    form.add_error("file", error)
            else:
                batch = StudentImportBatch.objects.create(
                    created_by=request.user,
                    filename=form.cleaned_data["file"].name[:255],
                    section=form.cleaned_data["section"],
                    academic_year=form.cleaned_data["academic_year"],
                    term=form.cleaned_data["term"],
                    rows=rows,
                    row_count=len(rows),
                )

                return redirect(
                    "student_onboarding:preview",
                    batch_id=batch.pk,
                )

    else:
        form = StudentImportForm()

    return render(
        request,
        "student_onboarding/upload.html",
        {"form": form},
    )


@login_required
def preview_import(request, batch_id):
    require_admin(request.user)

    batch = get_object_or_404(
        StudentImportBatch.objects.select_related(
            "section",
        ),
        pk=batch_id,
    )

    if batch.status == StudentImportBatch.Status.CONFIRMED:
        return redirect(
            "student_onboarding:batch_detail",
            batch_id=batch.pk,
        )

    return render(
        request,
        "student_onboarding/preview.html",
        {"batch": batch},
    )


@login_required
@require_POST
def confirm_students(request, batch_id):
    require_admin(request.user)

    try:
        with transaction.atomic():
            batch = confirm_import(batch_id)

    except StudentImportBatch.DoesNotExist:
        messages.error(
            request,
            "Import batch not found.",
        )

        return redirect(
            "student_onboarding:dashboard"
        )

    except ValidationError as exc:
        for error in exc.messages:
            messages.error(request, error)

        return redirect(
            "student_onboarding:preview",
            batch_id=batch_id,
        )

    except IntegrityError:
        messages.error(
            request,
            "A conflicting account was created while "
            "processing this import. No partial accounts "
            "were committed. Upload the file again.",
        )

        return redirect(
            "student_onboarding:dashboard"
        )

    messages.success(
        request,
        (
            f"{batch.created_count} inactive student "
            "accounts created successfully. "
            "Now send their activation emails."
        ),
    )

    return redirect(
        "student_onboarding:batch_detail",
        batch_id=batch.pk,
    )


@login_required
def batch_detail(request, batch_id):
    require_admin(request.user)

    batch = get_object_or_404(
        StudentImportBatch.objects.select_related(
            "section",
        ),
        pk=batch_id,
        status=StudentImportBatch.Status.CONFIRMED,
    )

    identities = (
        batch.identities
        .select_related("user")
        .order_by("roll_number")
    )

    context = {
        "batch": batch,
        "identities": identities[:100],
        "total": identities.count(),
        "pending": identities.filter(
            status=StudentIdentity.Status.PENDING
        ).count(),
        "activated": identities.filter(
            status=StudentIdentity.Status.ACTIVE
        ).count(),
        "sent": identities.filter(
            email_status=StudentIdentity.EmailStatus.SENT
        ).count(),
        "queued": identities.filter(
            email_status=StudentIdentity.EmailStatus.QUEUED
        ).count(),
        "failed": identities.filter(
            email_status=StudentIdentity.EmailStatus.FAILED
        ).count(),
    }

    return render(
        request,
        "student_onboarding/batch_detail.html",
        context,
    )


@login_required
@require_POST
def send_activation_emails(request, batch_id):
    require_admin(request.user)

    try:
        result = send_pending_activation_emails(
            batch_id,
            limit=25,
        )

    except (
        ValidationError,
        StudentImportBatch.DoesNotExist,
    ) as exc:
        messages.error(
            request,
            str(exc),
        )

    else:
        messages.success(
            request,
            (
                f"Email delivery completed: "
                f"{result.sent} sent, "
                f"{result.failed} failed."
            ),
        )

    return redirect(
        "student_onboarding:batch_detail",
        batch_id=batch_id,
    )


@login_required
def download_template(request):
    require_admin(request.user)

    response = HttpResponse(
        content_type="text/csv; charset=utf-8"
    )

    response["Content-Disposition"] = (
        'attachment; filename="assignhub_student_import.csv"'
    )

    response.write("\ufeff")

    writer = csv.writer(response)

    writer.writerow([
        "roll_number",
        "first_name",
        "last_name",
        "email",
    ])

    return response


def invalid_activation_response(request):
    response = render(
        request,
        "student_onboarding/invalid_link.html",
        status=400,
    )

    response["Referrer-Policy"] = "no-referrer"
    return response


@never_cache
def activate_student(request, token):
    """
    Password setup and class allocation are atomic.

    If allocation fails, the student remains
    inactive and the password is not committed.
    """

    identity = get_identity_from_token(token)

    if identity is None:
        return invalid_activation_response(request)

    user = identity.user

    if request.method == "POST":
        form = SetPasswordForm(
            user,
            request.POST,
        )

        if form.is_valid():
            try:
                with transaction.atomic():

                    locked_identity = (
                        StudentIdentity.objects
                        .select_for_update()
                        .select_related(
                            "user",
                            "section",
                            "import_batch",
                        )
                        .get(pk=identity.pk)
                    )

                    # Check token again inside transaction.
                    current_identity = get_identity_from_token(
                        token
                    )

                    if (
                        current_identity is None
                        or current_identity.pk != locked_identity.pk
                    ):
                        raise ValidationError(
                            "Activation link is no longer valid."
                        )

                    locked_user = (
                        User.objects.select_for_update()
                        .get(pk=locked_identity.user_id)
                    )

                    if locked_user.is_active:
                        raise ValidationError(
                            "Account is already active."
                        )

                    if not UserProfile.objects.filter(
                        user=locked_user,
                        role=UserProfile.Role.STUDENT,
                    ).exists():
                        raise ValidationError(
                            "Student profile is missing."
                        )

                    locked_user.set_password(
                        form.cleaned_data["new_password1"]
                    )

                    locked_user.is_active = True

                    locked_user.save(
                        update_fields=[
                            "password",
                            "is_active",
                        ]
                    )

                    # Existing allocation service:
                    # no duplicate enrollment logic.
                    allocate_students(
                        students=[locked_user],
                        section=locked_identity.section,
                        academic_year=(
                            locked_identity.academic_year
                        ),
                        term=locked_identity.term,
                        assigned_by=(
                            locked_identity.import_batch.created_by
                        ),
                        allow_transfer=False,
                        reason="Student account activation",
                    )

                    locked_identity.status = (
                        StudentIdentity.Status.ACTIVE
                    )

                    locked_identity.activated_at = timezone.now()

                    # Invalidate existing activation links.
                    locked_identity.activation_nonce = (
                        secrets.token_urlsafe(32)
                    )

                    locked_identity.save(
                        update_fields=[
                            "status",
                            "activated_at",
                            "activation_nonce",
                        ]
                    )

            except ValidationError as exc:
                for error in exc.messages:
                    form.add_error(None, error)

            except IntegrityError:
                form.add_error(
                    None,
                    "Account activation could not be completed. "
                    "Please contact university administration.",
                )

            else:
                messages.success(
                    request,
                    (
                        "Your student account is activated. "
                        "You can now sign in using your roll "
                        "number and password."
                    ),
                )

                return redirect("accounts:login")

    else:
        form = SetPasswordForm(user)

    response = render(
        request,
        "student_onboarding/activate.html",
        {
            "form": form,
            "identity": identity,
        },
    )

    response["Referrer-Policy"] = "same-origin"

    return response