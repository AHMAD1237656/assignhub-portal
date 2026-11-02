"""Persisted, restart-safe automatic plagiarism analysis queue.

The HTTP request only enqueues work. A separate management-command worker
executes expensive OCR and comparisons outside the request lifecycle.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections, transaction
from django.db.models import F
from django.utils import timezone

from .models import PlagiarismScan, Submission
from .similarity import analyze_submission, tokens

logger = logging.getLogger(__name__)
FINAL_STATUSES = (Submission.Status.SUBMITTED, Submission.Status.GRADED)


def _reset_pending(qs):
    return qs.update(
        status=PlagiarismScan.Status.QUEUED,
        version=F("version") + 1,
        started_at=None,
        error="",
        highest_lexical=None,
        highest_semantic=None,
        checked_count=0,
        match_count=0,
        result={},
        scanned_at=None,
    )


def queue_assignment(assignment_id):
    """Requeue EVERY finalized peer after a new submission arrives.

    This is crucial: the first submission has no peers, but the next student's
    submission must update the first student's result too.
    """
    ids = list(
        Submission.objects.filter(
            assignment_id=assignment_id,
            status__in=FINAL_STATUSES,
        ).values_list("pk", flat=True)
    )
    if not ids:
        return 0

    with transaction.atomic():
        PlagiarismScan.objects.bulk_create(
            [PlagiarismScan(submission_id=pk) for pk in ids],
            ignore_conflicts=True,
        )
        return _reset_pending(
            PlagiarismScan.objects.filter(submission_id__in=ids)
        )


def queue_one(submission):
    """Teacher-requested re-scan; does not requeue unrelated submissions."""
    if submission.status not in FINAL_STATUSES:
        raise ValueError("Only submitted or graded work can be scanned.")
    with transaction.atomic():
        PlagiarismScan.objects.get_or_create(submission=submission)
        return _reset_pending(
            PlagiarismScan.objects.filter(submission_id=submission.pk)
        )


def queue_missing_reports():
    """One-time backfill for work submitted before this feature was installed."""
    assignment_ids = list(
        Submission.objects.filter(status__in=FINAL_STATUSES)
        .order_by()
        .values_list("assignment_id", flat=True)
        .distinct()
    )
    total = 0
    for assignment_id in assignment_ids:
        total += queue_assignment(assignment_id)
    return total


def recover_stale_scans(minutes=30):
    """Recover interrupted worker jobs; bump version to reject stale results."""
    return _reset_pending(
        PlagiarismScan.objects.filter(
            status=PlagiarismScan.Status.RUNNING,
            started_at__lt=timezone.now() - timedelta(minutes=minutes),
        )
    )


def _compact_report(raw):
    source = raw["source"]
    return {
        "source": {
            "status": source.status,
            "pages": source.pages,
            "total_pages": source.total_pages,
            "confidence": source.confidence,
            "methods": list(source.methods),
            "warnings": list(source.warnings),
            "recognized_words": len(tokens(source.text)),
            "page_details": list(source.page_details),
        },
        "checked": raw["checked"],
        "limited": raw["limited"],
        "skipped": list(raw["skipped"]),
        "warnings": list(raw["warnings"]),
        "matches": [
            {
                "submission_id": match.submission.pk,
                "student": match.submission.student.username,
                "lexical": match.lexical,
                "semantic": match.semantic,
                "candidate_status": match.candidate_status,
                "passages": list(match.passages),
            }
            for match in raw["matches"]
        ],
        "analyzed_at": timezone.now().isoformat(),
    }


def _status(raw, lex_threshold, semantic_threshold):
    source = raw["source"]
    if not source.usable:
        return PlagiarismScan.Status.UNREADABLE

    flagged = any(
        match.lexical >= lex_threshold
        or (match.semantic is not None and match.semantic >= semantic_threshold)
        for match in raw["matches"]
    )
    if flagged:
        return PlagiarismScan.Status.NEEDS_REVIEW
    if raw["limited"] or raw["skipped"]:
        return PlagiarismScan.Status.PARTIAL
    if raw["checked"] == 0:
        return PlagiarismScan.Status.WAITING
    return PlagiarismScan.Status.NO_FLAG


def process_next():
    """Claim and process one queued row; safe from duplicate worker claims.

    Compare version on completion: a later submission may requeue this row
    while OCR is running. Old results must never overwrite newer pending work.
    """
    close_old_connections()
    queued = (
        PlagiarismScan.objects.filter(status=PlagiarismScan.Status.QUEUED)
        .order_by("updated_at", "pk")
        .values("pk", "version", "submission_id")
        .first()
    )
    if queued is None:
        return False

    scan_id = queued["pk"]
    version = queued["version"]
    claimed = PlagiarismScan.objects.filter(
        pk=scan_id,
        version=version,
        status=PlagiarismScan.Status.QUEUED,
    ).update(status=PlagiarismScan.Status.RUNNING, started_at=timezone.now())
    if not claimed:
        return True  # Another worker claimed it. Check for other work.

    try:
        submission = Submission.objects.select_related("assignment").get(
            pk=queued["submission_id"]
        )
        if submission.status not in FINAL_STATUSES:
            raise ValueError("Submission is no longer finalized")

        semantic = bool(getattr(settings, "PLAGIARISM_AUTO_SEMANTIC", False))
        lexical_threshold = float(
            getattr(settings, "PLAGIARISM_FLAG_LEXICAL_PERCENT", 35)
        )
        semantic_threshold = float(
            getattr(settings, "PLAGIARISM_FLAG_SEMANTIC_PERCENT", 85)
        )
        raw = analyze_submission(
            submission, mode="auto", use_semantic=semantic
        )
        compact = _compact_report(raw)
        compact["thresholds"] = {
            "lexical": lexical_threshold,
            "semantic": semantic_threshold,
        }
        sem_scores = [
            match.semantic
            for match in raw["matches"]
            if match.semantic is not None
        ]
        scan_status = _status(raw, lexical_threshold, semantic_threshold)
        updated = PlagiarismScan.objects.filter(
            pk=scan_id,
            version=version,
            status=PlagiarismScan.Status.RUNNING,
        ).update(
            status=scan_status,
            result=compact,
            checked_count=raw["checked"],
            match_count=len(raw["matches"]),
            highest_lexical=raw["highest_score"],
            highest_semantic=max(sem_scores) if sem_scores else None,
            scanned_at=timezone.now(),
            started_at=None,
            error="",
        )
        if updated and scan_status == PlagiarismScan.Status.NEEDS_REVIEW:
            try:
                from notifications.services import notify_plagiarism_flag
                notify_plagiarism_flag(submission.pk)
            except Exception:
                logger.exception("Could not create teacher integrity notification")

    except Exception:
        logger.exception("Automatic plagiarism analysis failed: scan=%s", scan_id)
        PlagiarismScan.objects.filter(
            pk=scan_id,
            version=version,
            status=PlagiarismScan.Status.RUNNING,
        ).update(
            status=PlagiarismScan.Status.FAILED,
            started_at=None,
            error="Automatic scan failed. Check the server worker log.",
        )
    finally:
        close_old_connections()
    return True
