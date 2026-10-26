from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import (
    AssignmentForm,
    GradeSubmissionForm,
    SubmissionForm,
)
from .models import Assignment, Submission


@login_required
def assignment_list(request):
    assignments = Assignment.objects.all()

    if not request.user.is_staff:
        assignments = assignments.filter(
            status=Assignment.Status.PUBLISHED
        )

    return render(
        request,
        "assignments/assignment_list.html",
        {
            "assignments": assignments,
        },
    )


@login_required
def assignment_detail(request, pk):
    assignment = get_object_or_404(
        Assignment,
        pk=pk,
    )

    if (
        not request.user.is_staff
        and assignment.status != Assignment.Status.PUBLISHED
    ):
        raise PermissionDenied

    submission = None

    if not request.user.is_staff:
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
        },
    )


@login_required
def assignment_create(request):

    if not request.user.is_staff:
        raise PermissionDenied

    if request.method == "POST":
        form = AssignmentForm(
            request.POST,
            request.FILES,
        )

        if form.is_valid():
            assignment = form.save(
                commit=False
            )

            assignment.created_by = request.user

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


@login_required
def assignment_edit(request, pk):

    assignment = get_object_or_404(
        Assignment,
        pk=pk,
    )

    if assignment.created_by != request.user:
        raise PermissionDenied

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


@login_required
def assignment_delete(request, pk):

    assignment = get_object_or_404(
        Assignment,
        pk=pk,
    )

    if assignment.created_by != request.user:
        raise PermissionDenied

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


@login_required
def submit_assignment(request, pk):

    assignment = get_object_or_404(
        Assignment,
        pk=pk,
        status=Assignment.Status.PUBLISHED,
    )

    if request.user.is_staff:
        raise PermissionDenied

    if timezone.now() > assignment.deadline:
        messages.error(
            request,
            "The assignment deadline has passed.",
        )

        return redirect(
            "assignments:detail",
            pk=assignment.pk,
        )

    submission = Submission.objects.filter(
        assignment=assignment,
        student=request.user,
    ).first()

    if submission and submission.status == Submission.Status.SUBMITTED:
        messages.info(
            request,
            "You have already submitted this assignment.",
        )

        return redirect(
            "assignments:detail",
            pk=assignment.pk,
        )

    if request.method == "POST":

        if submission:
            form = SubmissionForm(
                request.POST,
                request.FILES,
                instance=submission,
            )
        else:
            form = SubmissionForm(
                request.POST,
                request.FILES,
            )

        if form.is_valid():

            submission = form.save(
                commit=False
            )

            submission.assignment = assignment
            submission.student = request.user

            try:
                submission.submit()
            except ValidationError as error:
                form.add_error(
                    None,
                    error.message,
                )
            else:
                messages.success(
                    request,
                    "Assignment submitted successfully.",
                )

                return redirect(
                    "assignments:detail",
                    pk=assignment.pk,
                )

    else:

        if submission:
            form = SubmissionForm(
                instance=submission
            )
        else:
            form = SubmissionForm()

    return render(
        request,
        "assignments/submission_form.html",
        {
            "assignment": assignment,
            "form": form,
            "submission": submission,
        },
    )


@login_required
def submission_list(request):

    if request.user.is_staff:

        submissions = Submission.objects.select_related(
            "assignment",
            "student",
        )

    else:

        submissions = Submission.objects.filter(
            student=request.user
        ).select_related(
            "assignment"
        )

    return render(
        request,
        "assignments/submission_list.html",
        {
            "submissions": submissions,
        },
    )


@login_required
def submission_review(request, pk):

    submission = get_object_or_404(
        Submission.objects.select_related(
            "assignment",
            "student",
        ),
        pk=pk,
    )

    if submission.assignment.created_by != request.user:
        raise PermissionDenied

    if request.method == "POST":

        form = GradeSubmissionForm(
            request.POST,
            instance=submission,
        )

        if form.is_valid():

            submission = form.save(
                commit=False
            )

            submission.status = Submission.Status.GRADED
            submission.save()

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