
import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Q
from django.http import HttpResponse
from django.core.paginator import Paginator
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.views.decorators.http import require_POST

from .admin_forms import (
    CancelPendingStudentForm,
    PendingStudentEditForm,
    StudentDirectoryFilterForm,
)
from .admin_services import (
    cancel_pending_student,
    correct_pending_student,
    resend_individual_activation,
    restore_cancelled_student,
)
from .models import StudentIdentity
from .views import require_admin


def filtered_student_queryset(filter_form):
    queryset = (
        StudentIdentity.objects
        .select_related(
            "user",
            "section",
            "section__semester",
            "section__semester__program",
            "import_batch",
        )
        .order_by("roll_number", "pk")
    )

    if not filter_form.is_valid():
        return queryset

    data = filter_form.cleaned_data

    search = data.get("q", "").strip()
    status = data.get("status")
    email_status = data.get("email_status")
    section = data.get("section")

    if search:
        queryset = queryset.filter(
            Q(roll_number__icontains=search)
            | Q(user__first_name__icontains=search)
            | Q(user__last_name__icontains=search)
            | Q(institutional_email__icontains=search)
        )

    if status:
        queryset = queryset.filter(
            status=status
        )

    if email_status:
        queryset = queryset.filter(
            email_status=email_status
        )

    if section:
        queryset = queryset.filter(
            section=section
        )

    return queryset


@login_required
def student_directory(request):
    require_admin(request.user)

    filter_form = StudentDirectoryFilterForm(
        request.GET or None
    )

    queryset = filtered_student_queryset(
        filter_form
    )

    paginator = Paginator(queryset, 25)

    page_obj = paginator.get_page(
        request.GET.get("page")
    )

    query_params = request.GET.copy()
    query_params.pop("page", None)

    context = {
        "filter_form": filter_form,
        "page_obj": page_obj,
        "student_count": paginator.count,
        "querystring": query_params.urlencode(),
    }

    return render(
        request,
        "student_onboarding/student_list.html",
        context,
    )


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

    context = {
        "identity": identity,
        "edit_form": PendingStudentEditForm(
            identity=identity
        ),
        "cancel_form": CancelPendingStudentForm(),
        "events": events,
    }

    return render(
        request,
        "student_onboarding/student_detail.html",
        context,
    )


@login_required
@require_POST
def edit_student(request, identity_id):
    require_admin(request.user)

    identity = get_object_or_404(
        StudentIdentity.objects.select_related("user"),
        pk=identity_id,
    )

    form = PendingStudentEditForm(
        request.POST,
        identity=identity,
    )

    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, str(error))

        return redirect(
            "student_onboarding:student_detail",
            identity_id=identity.pk,
        )

    try:
        correct_pending_student(
            identity.pk,
            first_name=form.cleaned_data["first_name"],
            last_name=form.cleaned_data["last_name"],
            email=form.cleaned_data["email"],
            actor=request.user,
        )

    except ValidationError as exc:
        for error in exc.messages:
            messages.error(request, error)

    except IntegrityError:
        messages.error(
            request,
            "The email is already in use or the "
            "student record changed during this operation.",
        )

    else:
        messages.success(
            request,
            "Student information updated. "
            "Previous activation link invalidated. "
            "Send a new activation email.",
        )

    return redirect(
        "student_onboarding:student_detail",
        identity_id=identity.pk,
    )


@login_required
@require_POST
def cancel_student(request, identity_id):
    require_admin(request.user)

    identity = get_object_or_404(
        StudentIdentity,
        pk=identity_id,
    )

    form = CancelPendingStudentForm(
        request.POST
    )

    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, str(error))

        return redirect(
            "student_onboarding:student_detail",
            identity_id=identity.pk,
        )

    try:
        cancel_pending_student(
            identity.pk,
            reason=form.cleaned_data["reason"],
            actor=request.user,
        )

    except ValidationError as exc:
        for error in exc.messages:
            messages.error(request, error)

    else:
        messages.success(
            request,
            "Pending student account cancelled. "
            "Existing activation links are now invalid.",
        )

    return redirect(
        "student_onboarding:student_detail",
        identity_id=identity.pk,
    )


@login_required
@require_POST
def restore_student(request, identity_id):
    require_admin(request.user)

    identity = get_object_or_404(
        StudentIdentity,
        pk=identity_id,
    )

    try:
        restore_cancelled_student(
            identity.pk,
            actor=request.user,
        )

    except ValidationError as exc:
        for error in exc.messages:
            messages.error(request, error)

    else:
        messages.success(
            request,
            "Student restored to Pending Activation. "
            "You can send a fresh invitation now.",
        )

    return redirect(
        "student_onboarding:student_detail",
        identity_id=identity.pk,
    )


@login_required
@require_POST
def resend_student_email(request, identity_id):
    require_admin(request.user)

    identity = get_object_or_404(
        StudentIdentity,
        pk=identity_id,
    )

    try:
        success = resend_individual_activation(
            identity.pk,
            actor=request.user,
        )

    except ValidationError as exc:
        for error in exc.messages:
            messages.error(request, error)

    else:
        if success:
            messages.success(
                request,
                "A fresh activation email was sent.",
            )
        else:
            messages.error(
                request,
                "Activation email delivery failed. "
                "Check the mail backend configuration.",
            )

    return redirect(
        "student_onboarding:student_detail",
        identity_id=identity.pk,
    )


def csv_safe(value):
    """
    Prevent spreadsheet formula injection
    when CSV is opened in office software.
    """

    text = str(
        value if value is not None else ""
    )

    text = (
        text.replace("\r", " ")
        .replace("\n", " ")
        .replace("\t", " ")
    )

    if text.lstrip().startswith(
        ("=", "+", "-", "@")
    ):
        return "'" + text

    return text


@login_required
def export_student_report(request):
    require_admin(request.user)

    filter_form = StudentDirectoryFilterForm(
        request.GET or None
    )

    queryset = filtered_student_queryset(
        filter_form
    )

    response = HttpResponse(
        content_type="text/csv; charset=utf-8"
    )

    response["Content-Disposition"] = (
        'attachment; filename="assignhub_students_report.csv"'
    )

    # Excel-friendly UTF-8 BOM
    response.write("\ufeff")

    writer = csv.writer(response)

    writer.writerow([
        "roll_number",
        "first_name",
        "last_name",
        "email",
        "section",
        "academic_year",
        "term",
        "account_status",
        "email_status",
        "import_batch_id",
        "created_at",
        "activated_at",
        "cancelled_at",
    ])

    for identity in queryset.iterator(
        chunk_size=200
    ):
        writer.writerow([
            csv_safe(identity.roll_number),
            csv_safe(identity.user.first_name),
            csv_safe(identity.user.last_name),
            csv_safe(identity.institutional_email),
            csv_safe(str(identity.section)),
            csv_safe(identity.academic_year),
            csv_safe(identity.term),
            csv_safe(identity.status),
            csv_safe(identity.email_status),
            identity.import_batch_id,
            identity.created_at.isoformat(),
            (
                identity.activated_at.isoformat()
                if identity.activated_at
                else ""
            ),
            (
                identity.cancelled_at.isoformat()
                if identity.cancelled_at
                else ""
            ),
        ])

    return response
