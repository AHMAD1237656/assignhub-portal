from django.contrib import messages
from django.contrib.auth.decorators import login_required

from django.core.exceptions import PermissionDenied

from django.db import transaction

from django.http import FileResponse, Http404

from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)

from django.utils import timezone

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


# ==========================================
# Permission helpers
# ==========================================

def can_manage(request, assignment):
    return (
        is_teacher(request.user)
        and assignment.created_by_id == request.user.pk
    )


def can_view(request, assignment):
    if can_manage(request, assignment):
        return True

    if is_admin(request.user):
        return True

    if is_student(request.user):
        return (
            assignment.status
            == Assignment.Status.PUBLISHED
        )

    return False


# ==========================================
# Assignment list
# ==========================================

@login_required
def assignment_list(request):

    if is_teacher(request.user):
        assignments = Assignment.objects.filter(
            created_by=request.user
        )

    elif is_student(request.user):
        assignments = Assignment.objects.filter(
            status=Assignment.Status.PUBLISHED
        )

    elif is_admin(request.user):
        assignments = Assignment.objects.all()

    else:
        raise PermissionDenied

    return render(
        request,
        "assignments/assignment_list.html",
        {
            "assignments": assignments,
            "can_create": is_teacher(request.user),
        },
    )


# ==========================================
# Assignment detail
# ==========================================

@login_required
def assignment_detail(request, pk):

    assignment = get_object_or_404(
        Assignment,
        pk=pk,
    )

    if not can_view(request, assignment):
        raise PermissionDenied

    submission = None

    if is_student(request.user):
        submission = Submission.objects.filter(
            assignment=assignment,
            student=request.user,
        ).first()

    return render(
        request,
        "assignments/assignment_detail.html",
        {
            "assignment": assignment,
            "submission": submission,
            "can_manage": can_manage(
                request,
                assignment,
            ),
            "is_student_user": is_student(
                request.user
            ),
        },
    )


# ==========================================
# Create assignment
# ==========================================

@login_required
def assignment_create(request):

    if not is_teacher(request.user):
        raise PermissionDenied(
            "Only teachers can create assignments."
        )

    if request.method == "POST":
        form = AssignmentForm(
            request.POST,
            request.FILES,
        )

        if form.is_valid():
            assignment = form.save(commit=False)

            assignment.created_by = request.user

            assignment.full_clean()
            assignment.save()

            messages.success(
                request,
                "Assignment created successfully.",
            )

            return redirect(
                "assignments:detail",
                pk=assignment.pk,
            )

    else:
        form = AssignmentForm()

    return render(
        request,
        "assignments/assignment_form.html",
        {
            "form": form,
            "page_title": "Create Assignment",
        },
    )


# ==========================================
# Edit assignment
# ==========================================

@login_required
def assignment_edit(request, pk):

    assignment = get_object_or_404(
        Assignment,
        pk=pk,
    )

    if not can_manage(request, assignment):
        raise PermissionDenied(
            "You cannot edit this assignment."
        )

    has_final_submissions = (
        assignment.submissions.filter(
            status__in=[
                Submission.Status.SUBMITTED,
                Submission.Status.GRADED,
            ]
        ).exists()
    )

    if has_final_submissions:
        raise PermissionDenied(
            "Assignments with final submissions "
            "cannot be edited."
        )

    if request.method == "POST":
        form = AssignmentForm(
            request.POST,
            request.FILES,
            instance=assignment,
        )

        if form.is_valid():
            form.save()

            messages.success(
                request,
                "Assignment updated successfully.",
            )

            return redirect(
                "assignments:detail",
                pk=assignment.pk,
            )

    else:
        form = AssignmentForm(
            instance=assignment
        )

    return render(
        request,
        "assignments/assignment_form.html",
        {
            "form": form,
            "page_title": "Edit Assignment",
        },
    )


# ==========================================
# Delete assignment
# ==========================================

@login_required
def assignment_delete(request, pk):

    assignment = get_object_or_404(
        Assignment,
        pk=pk,
    )

    if not can_manage(request, assignment):
        raise PermissionDenied(
            "You cannot delete this assignment."
        )

    if assignment.submissions.exists():
        raise PermissionDenied(
            "Assignments with submissions "
            "cannot be deleted."
        )

    if request.method == "POST":

        assignment.delete()

        messages.success(
            request,
            "Assignment deleted successfully.",
        )

        return redirect(
            "assignments:list"
        )

    return render(
        request,
        "assignments/assignment_confirm_delete.html",
        {
            "assignment": assignment,
        },
    )


# ==========================================
# Student submission
# ==========================================

@login_required
def submit_assignment(request, pk):

    if not is_student(request.user):
        raise PermissionDenied(
            "Only students can submit assignments."
        )

    assignment = get_object_or_404(
        Assignment,
        pk=pk,
        status=Assignment.Status.PUBLISHED,
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
            "You have already finalized this submission."
        )

    if not assignment.is_open:
        raise PermissionDenied(
            "The submission window is closed."
        )

    if request.method == "POST":
        form = SubmissionForm(
            request.POST,
            request.FILES,
            instance=existing,
        )

        if form.is_valid():

            with transaction.atomic():

                assignment = (
                    Assignment.objects
                    .select_for_update()
                    .get(pk=assignment.pk)
                )

                current = (
                    Submission.objects
                    .select_for_update()
                    .filter(
                        assignment=assignment,
                        student=request.user,
                    )
                    .first()
                )

                if not assignment.is_open:
                    raise PermissionDenied(
                        "Assignment submission has closed."
                    )

                if (
                    current
                    and current.status
                    != Submission.Status.DRAFT
                ):
                    raise PermissionDenied(
                        "Submission already finalized."
                    )

                submission = form.save(
                    commit=False
                )

                if current:
                    submission.pk = current.pk

                submission.assignment = assignment
                submission.student = request.user

                submission.status = (
                    Submission.Status.SUBMITTED
                )

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

    else:
        form = SubmissionForm(
            instance=existing
        )

    return render(
        request,
        "assignments/submission_form.html",
        {
            "assignment": assignment,
            "submission": existing,
            "form": form,
        },
    )


# ==========================================
# Submission list
# ==========================================

@login_required
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

    submissions = submissions.select_related(
        "assignment",
        "student",
    )

    return render(
        request,
        "assignments/submission_list.html",
        {
            "submissions": submissions,
            "can_review": is_teacher(request.user),
            "is_student_user": is_student(request.user),
        },
    )


# ==========================================
# Teacher grading
# ==========================================

@login_required
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
        raise PermissionDenied(
            "You cannot review this submission."
        )

    if submission.status == Submission.Status.DRAFT:
        raise PermissionDenied(
            "Draft submissions cannot be graded."
        )

    if request.method == "POST":

        form = GradeSubmissionForm(
            request.POST,
            instance=submission,
        )

        if form.is_valid():

            submission = form.save(
                commit=False
            )

            submission.status = (
                Submission.Status.GRADED
            )

            submission.full_clean()

            submission.save(
                update_fields=[
                    "marks",
                    "feedback",
                    "status",
                    "updated_at",
                ]
            )

            messages.success(
                request,
                "Submission graded successfully.",
            )

            return redirect(
                "assignments:submissions"
            )

    else:
        form = GradeSubmissionForm(
            instance=submission
        )

    return render(
        request,
        "assignments/submission_review.html",
        {
            "submission": submission,
            "form": form,
        },
    )


# ==========================================
# Protected assignment file
# ==========================================

@login_required
def assignment_attachment(request, pk):

    assignment = get_object_or_404(
        Assignment,
        pk=pk,
    )

    if not can_view(request, assignment):
        raise PermissionDenied

    if not assignment.attachment:
        raise Http404(
            "No attachment available."
        )

    return FileResponse(
        assignment.attachment.open("rb"),
        as_attachment=True,
        filename=assignment.attachment.name.split("/")[-1],
    )


# ==========================================
# Protected submission file
# ==========================================

@login_required
def submission_attachment(request, pk):

    submission = get_object_or_404(
        Submission.objects.select_related(
            "assignment"
        ),
        pk=pk,
    )

    authorized = (
        is_admin(request.user)
        or can_manage(
            request,
            submission.assignment,
        )
        or (
            is_student(request.user)
            and submission.student_id
            == request.user.pk
        )
    )

    if not authorized:
        raise PermissionDenied

    if not submission.submission_file:
        raise Http404(
            "No submission file available."
        )

    return FileResponse(
        submission.submission_file.open("rb"),
        as_attachment=True,
        filename=(
            submission.submission_file.name
            .split("/")[-1]
        ),
    )