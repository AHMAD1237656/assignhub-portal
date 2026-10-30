import logging
import secrets
from django.urls import reverse
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import reverse
from django.template.loader import render_to_string
from django.utils import timezone

from class_allocations.models import StudentClassAllocation
from class_allocations.services import validate_section
from courses.models import CourseEnrollment

from .import_utils import inspect_existing_accounts
from .models import (
    StudentIdentity,
    StudentImportBatch,
)


logger = logging.getLogger(__name__)

User = get_user_model()

ACTIVATION_SALT = "assignhub.student.activation.v1"


@dataclass
class EmailDeliveryResult:
    sent: int = 0
    failed: int = 0


def activation_max_age():
    return getattr(
        settings,
        "STUDENT_ACTIVATION_MAX_AGE_SECONDS",
        172800,
    )


def validate_section_capacity(batch, new_count):
    section = batch.section

    validate_section(section)

    allocated_ids = set(
        StudentClassAllocation.objects.filter(
            section=section,
            academic_year=batch.academic_year,
            term=batch.term,
            status=StudentClassAllocation.Status.ACTIVE,
        ).values_list("student_id", flat=True)
    )

    enrolled_ids = set(
        CourseEnrollment.objects.filter(
            offering__section=section,
            offering__academic_year=batch.academic_year,
            offering__term=batch.term,
            status=CourseEnrollment.Status.ACTIVE,
        ).values_list("student_id", flat=True)
    )

    pending_ids = set(
        StudentIdentity.objects.filter(
            section=section,
            academic_year=batch.academic_year,
            term=batch.term,
            status=StudentIdentity.Status.PENDING,
        ).values_list("user_id", flat=True)
    )

    occupied_ids = (
        allocated_ids | enrolled_ids | pending_ids
    )

    free_seats = max(
        0,
        section.capacity - len(occupied_ids),
    )

    if new_count > free_seats:
        raise ValidationError(
            f"Only {free_seats} seats are available "
            "in this section for the selected academic period."
        )


@transaction.atomic
def confirm_import(batch_id):
    """
    Create all student accounts atomically.

    No account is made active here.
    No password is assigned here.
    """

    batch = (
        StudentImportBatch.objects
        .select_for_update()
        .select_related(
            "section",
            "section__semester",
            "section__semester__program",
            "section__semester__program__department",
        )
        .get(pk=batch_id)
    )

    if batch.status != StudentImportBatch.Status.PREVIEW:
        raise ValidationError(
            "This import has already been confirmed."
        )

    if batch.is_expired:
        raise ValidationError(
            "Import preview expired. Upload the file again."
        )

    rows = [
        {
            **row,
            "errors": list(row.get("errors", [])),
        }
        for row in batch.rows
    ]

    if not rows:
        raise ValidationError(
            "This import contains no students."
        )

    if any(row["errors"] for row in rows):
        raise ValidationError(
            "Resolve the preview errors before confirmation."
        )

    # Recheck in case accounts were created after preview.
    rows = inspect_existing_accounts(rows)

    if any(row["errors"] for row in rows):
        raise ValidationError(
            "Account data changed since preview. "
            "Upload the file again."
        )

    # Capacity is checked before creating anything.
    validate_section_capacity(
        batch,
        len(rows),
    )

    for row in rows:

        user = User(
            username=row["roll_number"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            email=row["email"],
            is_active=False,
            is_staff=False,
            is_superuser=False,
        )

        # No default or shared password.
        user.set_unusable_password()
        user.save()

        from accounts.models import UserProfile

        UserProfile.objects.create(
            user=user,
            role=UserProfile.Role.STUDENT,
        )

        StudentIdentity.objects.create(
            user=user,
            import_batch=batch,
            roll_number=row["roll_number"],
            institutional_email=row["email"],
            section=batch.section,
            academic_year=batch.academic_year,
            term=batch.term,
        )

    batch.status = StudentImportBatch.Status.CONFIRMED
    batch.created_count = len(rows)
    batch.confirmed_at = timezone.now()

    # Avoid retaining unnecessary preview PII.
    batch.rows = []

    batch.save(
        update_fields=[
            "status",
            "created_count",
            "confirmed_at",
            "rows",
        ]
    )

    return batch


def make_activation_token(identity, nonce=None):
    return signing.dumps(
        {
            "identity_id": identity.pk,
            "nonce": nonce or identity.activation_nonce,
        },
        salt=ACTIVATION_SALT,
    )


def get_identity_from_token(token):
    try:
        payload = signing.loads(
            token,
            salt=ACTIVATION_SALT,
            max_age=activation_max_age(),
        )
    except signing.BadSignature:
        return None

    if not isinstance(payload, dict):
        return None

    try:
        identity = (
            StudentIdentity.objects
            .select_related(
                "user",
                "section",
                "import_batch",
            )
            .get(
                pk=payload.get("identity_id")
            )
        )
    except (
        StudentIdentity.DoesNotExist,
        ValueError,
        TypeError,
    ):
        return None

    if identity.status != StudentIdentity.Status.PENDING:
        return None

    if identity.user.is_active:
        return None

    if identity.user.has_usable_password():
        return None

    if identity.activation_nonce != payload.get("nonce"):
        return None

    return identity


def eligible_email_filter(now):
    from django.db.models import Q

    expired_sent = (
        now - timedelta(
            seconds=activation_max_age()
        )
    )

    abandoned_sending = now - timedelta(minutes=15)

    return (
        Q(
            email_status__in=[
                StudentIdentity.EmailStatus.QUEUED,
                StudentIdentity.EmailStatus.FAILED,
            ]
        )
        | Q(
            email_status=StudentIdentity.EmailStatus.SENT,
            email_sent_at__lte=expired_sent,
        )
        | Q(
            email_status=StudentIdentity.EmailStatus.SENDING,
            email_claimed_at__lte=abandoned_sending,
        )
    )


def send_pending_activation_emails(batch_id, limit=25):
    """
    Send a bounded number of emails.

    A sent invitation can be reissued after expiry.
    Reissuing rotates its nonce and invalidates old links.
    """

    batch = StudentImportBatch.objects.get(
        pk=batch_id
    )

    if batch.status != StudentImportBatch.Status.CONFIRMED:
        raise ValidationError(
            "Import must be confirmed before sending emails."
        )

    limit = max(1, min(int(limit), 500))

    base_url = getattr(
        settings,
        "ASSIGNHUB_PUBLIC_BASE_URL",
        "",
    ).rstrip("/")

    if not base_url.startswith(("http://", "https://")):
        raise ValidationError(
            "ASSIGNHUB_PUBLIC_BASE_URL is not configured."
        )

    if not settings.DEBUG and not base_url.startswith("https://"):
        raise ValidationError(
            "Production activation URLs must use HTTPS."
        )

    now = timezone.now()

    candidates = list(
        StudentIdentity.objects.filter(
            import_batch=batch,
            status=StudentIdentity.Status.PENDING,
        )
        .filter(eligible_email_filter(now))
        .select_related("user")
        .order_by("pk")[:limit]
    )

    result = EmailDeliveryResult()

    for identity in candidates:

        nonce = secrets.token_urlsafe(32)
        claim_time = timezone.now()

        # Claim before performing the external email action.
        claimed = (
            StudentIdentity.objects.filter(
                pk=identity.pk,
                status=StudentIdentity.Status.PENDING,
            )
            .filter(eligible_email_filter(claim_time))
            .update(
                email_status=StudentIdentity.EmailStatus.SENDING,
                activation_nonce=nonce,
                email_claimed_at=claim_time,
            )
        )

        if not claimed:
            continue

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

        body = render_to_string(
            "student_onboarding/emails/activation.txt",
            {
                "student": identity.user,
                "roll_number": identity.roll_number,
                "activation_url": activation_url,
                "hours": activation_max_age() // 3600,
            },
        )

        try:
            sent = send_mail(
                subject="Activate your AssignHub student account",
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[
                    identity.institutional_email
                ],
                fail_silently=False,
            )

            if sent != 1:
                raise RuntimeError(
                    "Email backend did not accept the message."
                )

        except Exception:
            logger.exception(
                "Activation email failed for identity ID %s",
                identity.pk,
            )

            StudentIdentity.objects.filter(
                pk=identity.pk,
                status=StudentIdentity.Status.PENDING,
                activation_nonce=nonce,
            ).update(
                email_status=StudentIdentity.EmailStatus.FAILED,
            )

            result.failed += 1
            continue

        StudentIdentity.objects.filter(
            pk=identity.pk,
            status=StudentIdentity.Status.PENDING,
            activation_nonce=nonce,
        ).update(
            email_status=StudentIdentity.EmailStatus.SENT,
            email_sent_at=timezone.now(),
        )

        result.sent += 1

    return result