
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import (
    PermissionDenied,
    ValidationError,
)
import csv

from django.core.paginator import Paginator
from django.http import HttpResponse
from django.db.models import Count, Q
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.utils import timezone
from django.views.decorators.http import (
    require_http_methods,
)

from courses.models import CourseEnrollment

from .forms import (
    AssignmentForm,
    GradeSubmissionForm,
    SubmissionForm,
)
from .models import Assignment, Submission
from .permissions import (
    is_admin,
    is_student,
    is_teacher,
)


def can_manage(request, assignment):
    return (
        is_teacher(request.user)
        and assignment.created_by_id == request.user.pk
    )


def student_has_course_access(user, assignment):
    if not is_student(user):
        return False

    if assignment.status != Assignment.Status.PUBLISHED:
        return False

    if not assignment.course_offering_id:
        return False

    return CourseEnrollment.objects.filter(
        student=user,
        status=CourseEnrollment.Status.ACTIVE,
        offering_id=assignment.course_offering_id,
        offering__is_active=True,
        offering__course__is_active=True,
        offering__section__is_active=True,
        offering__course__semester__is_active=True,
        offering__course__program__is_active=True,
        offering__course__program__department__is_active=True,
    ).exists()


def can_view(request, assignment):
    return (
        can_manage(request, assignment)
        or is_admin(request.user)
        or student_has_course_access(
            request.user,
            assignment,
        )
    )


@login_required
@require_http_methods(["GET"])
def assignment_list(request):

    user = request.user

    if is_teacher(user):
        assignments = Assignment.objects.filter(
            created_by=user
        )

    elif is_student(user):
        assignments = Assignment.objects.filter(
            status=Assignment.Status.PUBLISHED,
            course_offering__is_active=True,
            course_offering__course__is_active=True,
            course_offering__section__is_active=True,
            course_offering__course__semester__is_active=True,
            course_offering__course__program__is_active=True,
            course_offering__course__program__department__is_active=True,
            course_offering__enrollments__student=user,
            course_offering__enrollments__status=(
                CourseEnrollment.Status.ACTIVE
            ),
        ).distinct()

    elif is_admin(user):
        assignments = Assignment.objects.all()

    else:
        raise PermissionDenied

    assignments = assignments.select_related(
        "created_by",
        "course_offering",
        "course_offering__course",
        "course_offering__course__program",
        "course_offering__section",
        "course_offering__section__semester",
        "course_offering__section__semester__program",
    )

    show_progress = (
        is_teacher(user) or is_admin(user)
    )

    if show_progress:
        assignments = assignments.annotate(
            enrolled_count=Count(
                "course_offering__enrollments",
                filter=Q(
                    course_offering__enrollments__status=(
                        CourseEnrollment.Status.ACTIVE
                    )
                ),
                distinct=True,
            ),
            submitted_count=Count(
                "submissions",
                filter=Q(
                    submissions__status__in=[
                        Submission.Status.SUBMITTED,
                        Submission.Status.GRADED,
                    ]
                ),
                distinct=True,
            ),
        )

    return render(
        request,
        "assignments/assignment_list.html",
        {
            "assignments": assignments,
            "can_create": is_teacher(user),
            "show_progress": show_progress,
        },
    )



@login_required
@require_http_methods(["GET"])
def assignment_detail(request, pk):

    assignment = get_object_or_404(
        Assignment.objects.select_related(
            "course_offering",
            "course_offering__course",
            "course_offering__section",
            "course_offering__section__semester",
            "course_offering__course__program",
            "created_by",
        ),
        pk=pk,
    )

    # Permission enforcement must happen before
    # rendering any assignment information.
    if not can_view(request, assignment):
        raise PermissionDenied

    user_is_student = is_student(request.user)

    teacher_can_manage = can_manage(
        request,
        assignment,
    )

    submission = None

    if user_is_student:
        submission = (
            Submission.objects.filter(
                assignment=assignment,
                student=request.user,
            )
            .first()
        )

    # Teacher cannot edit an assignment once
    # submitted/graded work exists.
    has_final_submissions = (
        assignment.submissions.filter(
            status__in=[
                Submission.Status.SUBMITTED,
                Submission.Status.GRADED,
            ]
        ).exists()
    )

    # Assignment deletion is blocked if any
    # submission record exists, including drafts.
    has_any_submissions = (
        assignment.submissions.exists()
    )

    context = {
        "assignment": assignment,
        "submission": submission,

        # Template permission flags
        "can_manage": teacher_can_manage,
        "is_student_user": user_is_student,

        # Workflow flags
        "has_final_submissions": has_final_submissions,
        "has_any_submissions": has_any_submissions,
    }

    return render(
        request,
        "assignments/assignment_detail.html",
        context,
    )


@login_required
@require_http_methods(["GET", "POST"])
def assignment_create(request):
    if not is_teacher(request.user):
        raise PermissionDenied

    form = AssignmentForm(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
        user=request.user,
    )

    if request.method == "POST" and form.is_valid():
        assignment = form.save(commit=False)
        assignment.created_by = request.user

        try:
            assignment.full_clean()
        except ValidationError as exc:
            for field, messages_list in (
                exc.message_dict.items()
                if hasattr(exc, "message_dict")
                else [(None, exc.messages)]
            ):
                if field not in form.fields:
                    field = None

                for error in messages_list:
                    form.add_error(field, error)
        else:
            assignment.save()

            messages.success(
                request,
                "Assignment created successfully.",
            )

            return redirect(
                "assignments:detail",
                pk=assignment.pk,
            )

    return render(
        request,
        "assignments/assignment_form.html",
        {
            "form": form,
            "page_title": "Create Assignment",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def assignment_edit(request, pk):
    assignment = get_object_or_404(
        Assignment,
        pk=pk,
    )

    if not can_manage(request, assignment):
        raise PermissionDenied
    # Assignment editing is locked once
    # any timed writing attempt has started.

    if (
        hasattr(assignment, "timed_writing_config")
        and assignment.timed_writing_config.attempts.exists()
    ):
        raise PermissionDenied(
            "Cannot edit assignment after "
            "a timed writing attempt has started."
        )
    if assignment.submissions.filter(
        status__in=[
            Submission.Status.SUBMITTED,
            Submission.Status.GRADED,
        ]
    ).exists():
        raise PermissionDenied(
            "Cannot edit after final submissions exist."
        )

    form = AssignmentForm(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
        instance=assignment,
        user=request.user,
    )

    if request.method == "POST" and form.is_valid():
        updated = form.save(commit=False)

        try:
            updated.full_clean()
        except ValidationError as exc:
            for field, messages_list in (
                exc.message_dict.items()
                if hasattr(exc, "message_dict")
                else [(None, exc.messages)]
            ):
                if field not in form.fields:
                    field = None

                for error in messages_list:
                    form.add_error(field, error)
        else:
            updated.save()
            form.save_m2m()

            messages.success(
                request,
                "Assignment updated.",
            )

            return redirect(
                "assignments:detail",
                pk=updated.pk,
            )

    return render(
        request,
        "assignments/assignment_form.html",
        {
            "form": form,
            "page_title": "Edit Assignment",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def assignment_delete(request, pk):
    assignment = get_object_or_404(
        Assignment,
        pk=pk,
    )

    if not can_manage(request, assignment):
        raise PermissionDenied

    if assignment.submissions.exists():
        raise PermissionDenied(
            "Cannot delete an assignment "
            "with submissions."
        )

    if request.method == "POST":
        assignment.delete()

        messages.success(
            request,
            "Assignment deleted.",
        )

        return redirect("assignments:list")

    return render(
        request,
        "assignments/assignment_confirm_delete.html",
        {"assignment": assignment},
    )


@login_required
@require_http_methods(["GET", "POST"])
def submit_assignment(request, pk):
    if not is_student(request.user):
        raise PermissionDenied

    assignment = get_object_or_404(
        Assignment,
        pk=pk,
        status=Assignment.Status.PUBLISHED,
    )

    if not student_has_course_access(
        request.user,
        assignment,
    ):
        raise PermissionDenied(
            "You are not enrolled in this course offering."
        )
    # Timed assignments cannot be submitted
    # through the ordinary submission form.

    if (
        hasattr(assignment, "timed_writing_config")
        and assignment.timed_writing_config.is_enabled
    ):
        if request.method == "GET":
            return redirect(
                "timed_writing:editor",
                assignment_pk=assignment.pk,
            )

        raise PermissionDenied(
            "Use the timed writing editor "
            "for this assignment."
        )   

    existing = Submission.objects.filter(
        assignment=assignment,
        student=request.user,
    ).first()

    if (
        existing
        and existing.status != Submission.Status.DRAFT
    ):
        raise PermissionDenied(
            "Submission already finalized."
        )

    if not assignment.is_open:
        raise PermissionDenied(
            "Submission window is closed."
        )

    form = SubmissionForm(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
        instance=existing,
    )

    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            assignment = (
                Assignment.objects.select_for_update()
                .get(pk=assignment.pk)
            )
            if (
                hasattr(assignment, "timed_writing_config")
                and assignment.timed_writing_config.is_enabled
            ):
                raise PermissionDenied(
                    "Use the timed writing editor "
                    "for this assignment."
                )
            current = (
                Submission.objects.select_for_update()
                .filter(
                    assignment=assignment,
                    student=request.user,
                )
                .first()
            )

            if (
                not assignment.is_open
                or not student_has_course_access(
                    request.user,
                    assignment,
                )
                or (
                    current
                    and current.status != Submission.Status.DRAFT
                )
            ):
                raise PermissionDenied(
                    "Submission is no longer allowed."
                )

            submission = form.save(commit=False)

            if current:
                submission.pk = current.pk

            submission.assignment = assignment
            submission.student = request.user
            submission.status = Submission.Status.SUBMITTED
            submission.submitted_at = timezone.now()

            submission.full_clean()
            submission.save()

        messages.success(
            request,
            "Assignment submitted successfully.",
        )

        return redirect(
            "assignments:detail",
            pk=assignment.pk,
        )

    return render(
        request,
        "assignments/submission_form.html",
        {
            "assignment": assignment,
            "form": form,
            "submission": existing,
        },
    )



@login_required
@require_http_methods(["GET"])
def submission_list(request):
    """
    AssignHub - Professional Submission Directory

    Features:
    - Role-based data isolation
    - Search and server-side filtering
    - Status/course filters
    - Sorting and pagination
    - Filtered CSV export for Admin/Teacher
    - AJAX-compatible HTML responses

    Uses the existing URL and template.
    """

    user = request.user

    teacher_user = is_teacher(user)
    student_user = is_student(user)
    admin_user = is_admin(user)

    # ======================================
    # ROLE-BASED QUERYSET
    # ======================================

    if teacher_user:
        base_queryset = Submission.objects.filter(
            assignment__created_by=user
        )

    elif student_user:
        base_queryset = Submission.objects.filter(
            student=user
        )

    elif admin_user:
        base_queryset = Submission.objects.all()

    else:
        raise PermissionDenied(
            "You cannot access submission records."
        )

    # ======================================
    # GLOBAL SUMMARY STATISTICS
    # ======================================

    summary = base_queryset.aggregate(
        total=Count("pk"),

        draft=Count(
            "pk",
            filter=Q(
                status=Submission.Status.DRAFT
            ),
        ),

        submitted=Count(
            "pk",
            filter=Q(
                status=Submission.Status.SUBMITTED
            ),
        ),

        graded=Count(
            "pk",
            filter=Q(
                status=Submission.Status.GRADED
            ),
        ),
    )

    # ======================================
    # ACCESSIBLE COURSE FILTER OPTIONS
    # ======================================

    course_rows = (
        base_queryset
        .exclude(
            assignment__course_offering__isnull=True
        )
        .values(
            "assignment__course_offering_id",
            "assignment__course_offering__course__code",
            "assignment__course_offering__section__code",
            "assignment__course_offering__academic_year",
        )
        .distinct()
        .order_by(
            "assignment__course_offering__course__code",
            "assignment__course_offering__section__code",
            "assignment__course_offering__academic_year",
        )
    )

    course_choices = []

    for row in course_rows:
        offering_id = row[
            "assignment__course_offering_id"
        ]

        course_code = (
            row[
                "assignment__course_offering__course__code"
            ]
            or "Course"
        )

        section_code = (
            row[
                "assignment__course_offering__section__code"
            ]
            or "Section"
        )

        academic_year = (
            row[
                "assignment__course_offering__academic_year"
            ]
            or ""
        )

        course_choices.append({
            "id": str(offering_id),
            "label": (
                f"{course_code} · "
                f"{section_code} · "
                f"{academic_year}"
            ),
        })

    # ======================================
    # READ FILTER PARAMETERS
    # ======================================

    search_query = (
        request.GET.get("q", "").strip()[:100]
    )

    status_filter = (
        request.GET.get("status", "")
        .strip()
        .upper()
    )

    course_filter = (
        request.GET.get("course", "")
        .strip()
    )

    sort_filter = (
        request.GET.get("sort", "newest")
        .strip()
    )

    submissions = base_queryset

    # ======================================
    # SEARCH
    # ======================================

    if search_query:
        submissions = submissions.filter(
            Q(
                assignment__title__icontains=(
                    search_query
                )
            )
            | Q(
                student__username__icontains=(
                    search_query
                )
            )
            | Q(
                student__first_name__icontains=(
                    search_query
                )
            )
            | Q(
                student__last_name__icontains=(
                    search_query
                )
            )
            | Q(
                assignment__course_offering__course__code__icontains=(
                    search_query
                )
            )
            | Q(
                assignment__course_offering__course__title__icontains=(
                    search_query
                )
            )
        )

    # ======================================
    # STATUS FILTER
    # ======================================

    valid_statuses = {
        Submission.Status.DRAFT,
        Submission.Status.SUBMITTED,
        Submission.Status.GRADED,
    }

    if status_filter:
        if status_filter in valid_statuses:
            submissions = submissions.filter(
                status=status_filter
            )
        else:
            submissions = submissions.none()

    # ======================================
    # COURSE FILTER
    # ======================================

    allowed_course_ids = {
        option["id"]
        for option in course_choices
    }

    if course_filter:
        if course_filter in allowed_course_ids:
            submissions = submissions.filter(
                assignment__course_offering_id=(
                    int(course_filter)
                )
            )
        else:
            submissions = submissions.none()

    # ======================================
    # SORTING
    # ======================================

    sort_options = {
        "newest": (
            "-submitted_at",
            "-created_at",
            "-pk",
        ),

        "oldest": (
            "submitted_at",
            "created_at",
            "pk",
        ),

        "assignment": (
            "assignment__title",
            "-pk",
        ),

        "student": (
            "student__username",
            "-pk",
        ),
    }

    if student_user and sort_filter == "student":
        sort_filter = "newest"

    if sort_filter not in sort_options:
        sort_filter = "newest"

    submissions = (
        submissions
        .select_related(
            "assignment",
            "assignment__course_offering",
            "assignment__course_offering__course",
            "assignment__course_offering__section",
            "student",
        )
        .order_by(*sort_options[sort_filter])
    )

    # ======================================
    # FILTERED CSV EXPORT
    # Admin and Teacher only
    # ======================================

    if request.GET.get("export") == "csv":

        if student_user:
            raise PermissionDenied(
                "Student accounts cannot export "
                "submission management reports."
            )

        response = HttpResponse(
            content_type="text/csv; charset=utf-8"
        )

        response["Content-Disposition"] = (
            'attachment; filename='
            '"assignhub_submissions.csv"'
        )

        # UTF-8 BOM for Excel compatibility.
        response.write("\ufeff")

        writer = csv.writer(response)

        writer.writerow([
            "Assignment",
            "Student Username",
            "Student Name",
            "Course",
            "Section",
            "Status",
            "Submitted At",
            "Marks",
            "Total Marks",
        ])

        def safe_csv_value(value):
            text = str(
                value if value is not None else ""
            )

            text = (
                text.replace("\r", " ")
                .replace("\n", " ")
                .replace("\t", " ")
                .replace("\x00", "")
            )

            # Prevent spreadsheet formula injection.
            if text.lstrip().startswith(
                ("=", "+", "-", "@")
            ):
                return "'" + text

            return text

        for submission in submissions.iterator(
            chunk_size=250
        ):

            assignment = submission.assignment
            offering = assignment.course_offering

            course_code = (
                offering.course.code
                if offering
                else ""
            )

            section_code = (
                offering.section.code
                if offering
                else ""
            )

            submitted_at = (
                timezone.localtime(
                    submission.submitted_at
                ).strftime("%Y-%m-%d %H:%M")
                if submission.submitted_at
                else ""
            )

            marks = (
                submission.marks
                if (
                    submission.status
                    == Submission.Status.GRADED
                )
                else ""
            )

            writer.writerow([
                safe_csv_value(assignment.title),
                safe_csv_value(
                    submission.student.username
                ),
                safe_csv_value(
                    submission.student.get_full_name()
                ),
                safe_csv_value(course_code),
                safe_csv_value(section_code),
                safe_csv_value(
                    submission.get_status_display()
                ),
                submitted_at,
                marks,
                assignment.total_marks,
            ])

        return response

    # ======================================
    # PAGINATION
    # ======================================

    paginator = Paginator(
        submissions,
        15,
    )

    page_obj = paginator.get_page(
        request.GET.get("page")
    )

    # Preserve filters in pagination URLs.
    query_params = request.GET.copy()

    query_params.pop("page", None)
    query_params.pop("export", None)

    filter_querystring = query_params.urlencode()

    # ======================================
    # RENDER
    # ======================================

    context = {
        "submissions": page_obj.object_list,
        "page_obj": page_obj,
        "filtered_count": paginator.count,

        "summary": summary,

        "search_query": search_query,
        "status_filter": status_filter,
        "course_filter": course_filter,
        "sort_filter": sort_filter,

        "course_choices": course_choices,
        "filter_querystring": filter_querystring,

        "is_teacher_user": teacher_user,
        "is_student_user": student_user,
        "is_admin_user": admin_user,

        "can_review": teacher_user,
    }

    return render(
        request,
        "assignments/submission_list.html",
        context,
    )


@login_required
@require_http_methods(["GET", "POST"])
def submission_review(request, pk):
    submission = get_object_or_404(
        Submission.objects.select_related(
            "assignment",
            "student",
        ),
        pk=pk,
    )

    if not can_manage(
        request,
        submission.assignment,
    ):
        raise PermissionDenied

    if submission.status == Submission.Status.DRAFT:
        raise PermissionDenied(
            "Draft submissions cannot be graded."
        )

    form = GradeSubmissionForm(
        request.POST if request.method == "POST" else None,
        instance=submission,
    )

    if request.method == "POST" and form.is_valid():
        graded = form.save(commit=False)
        graded.status = Submission.Status.GRADED
        graded.full_clean()

        graded.save(
            update_fields=[
                "marks",
                "feedback",
                "status",
                "updated_at",
            ]
        )

        messages.success(
            request,
            "Submission graded.",
        )

        return redirect("assignments:submissions")

    return render(
        request,
        "assignments/submission_review.html",
        {
            "submission": submission,
            "form": form,
        },
    )


@login_required
@require_http_methods(["GET"])
def assignment_attachment(request, pk):
    assignment = get_object_or_404(
        Assignment,
        pk=pk,
    )

    if not can_view(request, assignment):
        raise PermissionDenied

    if not assignment.attachment:
        raise Http404

    return FileResponse(
        assignment.attachment.open("rb"),
        as_attachment=True,
        filename=assignment.attachment.name.split("/")[-1],
    )


@login_required
@require_http_methods(["GET"])
def submission_attachment(request, pk):
    submission = get_object_or_404(
        Submission.objects.select_related("assignment"),
        pk=pk,
    )

    is_owner = (
        is_student(request.user)
        and submission.student_id == request.user.pk
    )

    if not (
        is_admin(request.user)
        or can_manage(
            request,
            submission.assignment,
        )
        or is_owner
    ):
        raise PermissionDenied

    if not submission.submission_file:
        raise Http404

    return FileResponse(
        submission.submission_file.open("rb"),
        as_attachment=True,
        filename=(
            submission.submission_file.name.split("/")[-1]
        ),
    )

from django.views.decorators.http import require_POST


@login_required
@require_POST
def assignment_close(request, pk):
    assignment = get_object_or_404(
        Assignment,
        pk=pk,
    )

    if not can_manage(request, assignment):
        raise PermissionDenied

    # Prevent closing while students
    # still have active timed attempts.
    if (
        hasattr(assignment, "timed_writing_config")
        and assignment.timed_writing_config.attempts.filter(
            status="ACTIVE",
            expires_at__gt=timezone.now(),
        ).exists()
    ):
        raise PermissionDenied(
            "Cannot close assignment during "
            "an active timed attempt."
        )

    if assignment.status != Assignment.Status.PUBLISHED:
        messages.error(
            request,
            "Only published assignments can be closed.",
        )
        return redirect(
            "assignments:detail",
            pk=assignment.pk,
        )

    assignment.status = Assignment.Status.CLOSED
    assignment.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    messages.success(
        request,
        "Assignment closed successfully.",
    )

    return redirect(
        "assignments:detail",
        pk=assignment.pk,
    )

@login_required
@require_http_methods(["GET"])
def assignment_roster(request, pk):

    assignment = get_object_or_404(
        Assignment.objects.select_related(
            "course_offering",
            "course_offering__course",
            "course_offering__section",
            "course_offering__section__semester",
        ),
        pk=pk,
    )

    if not (
        can_manage(request, assignment)
        or is_admin(request.user)
    ):
        raise PermissionDenied(
            "You cannot view this assignment's students."
        )

    enrolled_students = []

    if assignment.course_offering_id:
        enrolled_students = (
            CourseEnrollment.objects.filter(
                offering_id=assignment.course_offering_id,
                status=CourseEnrollment.Status.ACTIVE,
            )
            .select_related("student")
            .order_by("student__username")
        )

    submissions = (
        Submission.objects
        .filter(assignment=assignment)
        .select_related(
            "student",
            "timed_attempt",
        )
    )

    submission_map = {
        submission.student_id: submission
        for submission in submissions
    }

    student_rows = []

    submitted_count = 0
    graded_count = 0
    draft_count = 0

    for enrollment in enrolled_students:

        student = enrollment.student

        submission = submission_map.get(
            student.pk
        )

        if submission is None:
            status = "NOT_SUBMITTED"

        elif submission.status == Submission.Status.GRADED:
            status = "GRADED"
            graded_count += 1
            submitted_count += 1

        elif submission.status == Submission.Status.SUBMITTED:
            status = "SUBMITTED"
            submitted_count += 1

        else:
            # The submission is still a draft.
            # Check whether its timed attempt expired.
            timed_attempt = getattr(
                submission,
                "timed_attempt",
                None,
            )

            if (
                timed_attempt is not None
                and timed_attempt.status == "EXPIRED"
            ):
                status = "EXPIRED"

            elif (
                timed_attempt is not None
                and timed_attempt.status == "ACTIVE"
                and timed_attempt.expires_at <= timezone.now()
            ):
                # Expired by clock, but settlement has
                # not yet updated the database.
                status = "EXPIRY_PENDING"

            else:
                status = "DRAFT"
                draft_count += 1

        student_rows.append({
            "student": student,
            "submission": submission,
            "status": status,
        })

    total_students = len(student_rows)

    pending_count = (
        total_students - submitted_count
    )

    return render(
        request,
        "assignments/assignment_roster.html",
        {
            "assignment": assignment,
            "student_rows": student_rows,
            "total_students": total_students,
            "submitted_count": submitted_count,
            "graded_count": graded_count,
            "draft_count": draft_count,
            "pending_count": pending_count,
        },
    )