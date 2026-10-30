
import logging
import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import (
    StudentIdentity,
    StudentOnboardingEvent,
)
from .services import (
    activation_max_age,
    make_activation_token,
    validate_section_capacity,
)


logger = logging.getLogger(__name__)


def ensure_pending(identity):
    """
    Only an inactive, unconfigured student
    account can be edited or cancelled.
    """

    if identity.status != StudentIdentity.Status.PENDING:
        raise ValidationError(
            "Only pending student accounts can be modified."
        )

    if identity.user.is_active:
        raise ValidationError(
            "This account is already active."
        )

    if identity.user.has_usable_password():
        raise ValidationError(
            "This account already has a usable password."
        )


@transaction.atomic
def correct_pending_student(
    identity_id,
    *,
    first_name,
    last_name,
    email,
    actor,
):
    identity = (
        StudentIdentity.objects
        .select_for_update()
        .select_related("user")
        .get(pk=identity_id)
    )

    user = identity.user

    ensure_pending(identity)

    first_name = first_name.strip()
    last_name = last_name.strip()
    email = email.strip().lower()

    if not first_name or not last_name:
        raise ValidationError(
            "First and last names are required."
        )

    from .admin_forms import PendingStudentEditForm

    validator = PendingStudentEditForm(
        {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
        },
        identity=identity,
    )

    if not validator.is_valid():
        raise ValidationError(
            "Student information failed validation."
        )

    fields_changed = []

    if user.first_name != first_name:
        fields_changed.append("First name")

    if user.last_name != last_name:
        fields_changed.append("Last name")

    if (
        identity.institutional_email.lower()
        != email
    ):
        fields_changed.append("Email")

    if not fields_changed:
        raise ValidationError(
            "No changes were detected."
        )

    user.first_name = first_name
    user.last_name = last_name
    user.email = email

    user.save(
        update_fields=[
            "first_name",
            "last_name",
            "email",
        ]
    )

    identity.institutional_email = email

    # Any previously issued link is now invalid.
    identity.activation_nonce = secrets.token_urlsafe(32)

    identity.email_status = (
        StudentIdentity.EmailStatus.QUEUED
    )

    identity.email_claimed_at = None
    identity.email_sent_at = None

    identity.save(
        update_fields=[
            "institutional_email",
            "activation_nonce",
            "email_status",
            "email_claimed_at",
            "email_sent_at",
        ]
    )

    StudentOnboardingEvent.objects.create(
        identity=identity,
        actor=actor,
        action=StudentOnboardingEvent.Action.CORRECTED,
        details=(
            "Updated: "
            + ", ".join(fields_changed)
            + ". Previous activation link invalidated."
        ),
    )

    return identity


@transaction.atomic
def cancel_pending_student(
    identity_id,
    *,
    reason,
    actor,
):
    identity = (
        StudentIdentity.objects
        .select_for_update()
        .select_related("user")
        .get(pk=identity_id)
    )

    ensure_pending(identity)

    reason = reason.strip()

    if len(reason) < 8 or len(reason) > 200:
        raise ValidationError(
            "Cancellation reason must contain "
            "8 to 200 characters."
        )

    identity.status = StudentIdentity.Status.CANCELLED
    identity.cancelled_at = timezone.now()
    identity.cancelled_by = actor
    identity.cancellation_reason = reason

    # Immediately revoke any outstanding email link.
    identity.activation_nonce = secrets.token_urlsafe(32)

    identity.save(
        update_fields=[
            "status",
            "cancelled_at",
            "cancelled_by",
            "cancellation_reason",
            "activation_nonce",
        ]
    )

    StudentOnboardingEvent.objects.create(
        identity=identity,
        actor=actor,
        action=StudentOnboardingEvent.Action.CANCELLED,
        details=reason,
    )

    return identity


@transaction.atomic
def restore_cancelled_student(
    identity_id,
    *,
    actor,
):
    identity = (
        StudentIdentity.objects
        .select_for_update()
        .select_related(
            "user",
            "import_batch",
            "import_batch__section",
        )
        .get(pk=identity_id)
    )

    if identity.status != StudentIdentity.Status.CANCELLED:
        raise ValidationError(
            "Only cancelled accounts can be restored."
        )

    if (
        identity.user.is_active
        or identity.user.has_usable_password()
    ):
        raise ValidationError(
            "This student account cannot be safely restored."
        )

    # Restoring an account reserves one seat again.
    validate_section_capacity(
        identity.import_batch,
        new_count=1,
    )

    identity.status = StudentIdentity.Status.PENDING

    identity.cancelled_at = None
    identity.cancelled_by = None
    identity.cancellation_reason = ""

    identity.activation_nonce = secrets.token_urlsafe(32)

    identity.email_status = (
        StudentIdentity.EmailStatus.QUEUED
    )
    identity.email_claimed_at = None
    identity.email_sent_at = None

    identity.save(
        update_fields=[
            "status",
            "cancelled_at",
            "cancelled_by",
            "cancellation_reason",
            "activation_nonce",
            "email_status",
            "email_claimed_at",
            "email_sent_at",
        ]
    )

    StudentOnboardingEvent.objects.create(
        identity=identity,
        actor=actor,
        action=StudentOnboardingEvent.Action.RESTORED,
        details=(
            "Account restored to pending activation. "
            "A new invitation is required."
        ),
    )

    return identity


def resend_individual_activation(identity_id, *, actor):
    """
    Send a fresh invitation to one specific student.

    A new nonce invalidates earlier activation links.
    The database claim prevents two simultaneous
    requests from sending the same invitation.
    """

    identity = (
        StudentIdentity.objects
        .select_related("user")
        .get(pk=identity_id)
    )

    ensure_pending(identity)

    base_url = getattr(
        settings,
        "ASSIGNHUB_PUBLIC_BASE_URL",
        "",
    ).rstrip("/")

    if not base_url.startswith(("http://", "https://")):
        raise ValidationError(
            "ASSIGNHUB_PUBLIC_BASE_URL is not configured."
        )

    if not settings.DEBUG and not base_url.startswith(
        "https://"
    ):
        raise ValidationError(
            "Production activation links must use HTTPS."
        )

    nonce = secrets.token_urlsafe(32)
    claim_time = timezone.now()

    # Optimistic concurrency guard.
    claimed = (
        StudentIdentity.objects
        .filter(
            pk=identity.pk,
            status=StudentIdentity.Status.PENDING,
            activation_nonce=identity.activation_nonce,
            user__is_active=False,
        )
        .update(
            activation_nonce=nonce,
            email_status=StudentIdentity.EmailStatus.SENDING,
            email_claimed_at=claim_time,
        )
    )

    if not claimed:
        raise ValidationError(
            "Student record changed. Refresh the page and retry."
        )

    token = make_activation_token(
        identity,
        nonce=nonce,
    )

    activation_url = (
        base_url
        + reverse(
            "student_onboarding:activate",
            kwargs={"token": token},
        )
    )

    message = render_to_string(
        "student_onboarding/emails/activation.txt",
        {
            "student": identity.user,
            "roll_number": identity.roll_number,
            "activation_url": activation_url,
            "hours": activation_max_age() // 3600,
        },
    )

    try:
        result = send_mail(
            subject="Activate your AssignHub student account",
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[
                identity.institutional_email
            ],
            fail_silently=False,
        )

        if result != 1:
            raise RuntimeError(
                "Email backend did not accept the message."
            )

    except Exception:
        logger.exception(
            "Activation resend failed for student ID %s",
            identity.pk,
        )

        StudentIdentity.objects.filter(
            pk=identity.pk,
            status=StudentIdentity.Status.PENDING,
            activation_nonce=nonce,
        ).update(
            email_status=StudentIdentity.EmailStatus.FAILED,
        )

        StudentOnboardingEvent.objects.create(
            identity=identity,
            actor=actor,
            action=StudentOnboardingEvent.Action.EMAIL_FAILED,
            details="Individual activation email failed.",
        )

        return False

    StudentIdentity.objects.filter(
        pk=identity.pk,
        status=StudentIdentity.Status.PENDING,
        activation_nonce=nonce,
    ).update(
        email_status=StudentIdentity.EmailStatus.SENT,
        email_sent_at=timezone.now(),
    )

    StudentOnboardingEvent.objects.create(
        identity=identity,
        actor=actor,
        action=StudentOnboardingEvent.Action.EMAIL_RESENT,
        details=(
            "Fresh activation email sent. "
            "Previous invitation invalidated."
        ),
    )

    return True
