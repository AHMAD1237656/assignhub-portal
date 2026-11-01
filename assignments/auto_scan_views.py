"""Teacher-only access to persisted automatic scan results and re-scan."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from .auto_plagiarism import queue_one
from .models import PlagiarismScan, Submission
from .views import can_manage


def allowed_submission(request, pk):
    submission = get_object_or_404(
        Submission.objects.select_related("assignment", "student"), pk=pk
    )
    if not can_manage(request, submission.assignment):
        raise PermissionDenied("Only the assignment owner may view scan results.")
    if submission.status == Submission.Status.DRAFT:
        raise PermissionDenied("Draft work is not eligible for integrity review.")
    return submission


@login_required
@require_GET
def auto_scan_report(request, pk):
    submission = allowed_submission(request, pk)
    scan = PlagiarismScan.objects.filter(submission=submission).first()
    return render(request, "assignments/auto_scan_report.html", {
        "submission": submission,
        "scan": scan,
    })


@login_required
@require_POST
def auto_scan_retry(request, pk):
    submission = allowed_submission(request, pk)
    queue_one(submission)
    messages.success(request, "A fresh background plagiarism scan was queued.")
    return redirect("assignments:auto_scan_report", pk=submission.pk)
