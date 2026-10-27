
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import (
    PermissionDenied,
    ValidationError,
)
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
    if is_teacher(request.user):
        assignments = Assignment.objects.filter(
            created_by=request.user
        )

    elif is_student(request.user):
        assignments = Assignment.objects.filter(
            status=Assignment.Status.PUBLISHED,
            course_offering__is_active=True,
            course_offering__course__is_active=True,
            course_offering__section__is_active=True,
            course_offering__course__semester__is_active=True,
            course_offering__course__program__is_active=True,
            course_offering__course__program__department__is_active=True,
            course_offering__enrollments__student=request.user,
            course_offering__enrollments__status=(
                CourseEnrollment.Status.ACTIVE
            ),
        ).distinct()

    elif is_admin(request.user):
        assignments = Assignment.objects.all()

    else:
        raise PermissionDenied

    return render(
        request,
        "assignments/assignment_list.html",
        {
            "assignments": assignments.select_related(
                "course_offering",
                "created_by",
            ),
            "can_create": is_teacher(request.user),
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
    if is_teacher(request.user):
        submissions = Submission.objects.filter(
            assignment__created_by=request.user
        )

    elif is_student(request.user):
        submissions = Submission.objects.filter(
            student=request.user
        )

    elif is_admin(request.user):
        submissions = Submission.objects.all()

    else:
        raise PermissionDenied

    return render(
        request,
        "assignments/submission_list.html",
        {
            "submissions": submissions.select_related(
                "assignment",
                "student",
            )
        },
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
