import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import (
    PermissionDenied,
    ValidationError,
)
from django.http import JsonResponse
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import (
    require_GET,
    require_http_methods,
    require_POST,
)

from assignments.models import Assignment, Submission
from assignments.permissions import is_teacher

from .forms import TimedWritingConfigForm
from .models import TimedWritingAttempt, TimedWritingConfig
from .services import (
    begin,
    enforce_config,
    enforce_student,
    read_attempt,
    write_answer,
)


def server_seconds(value):
    return int(value.timestamp())


def payload(attempt):
    return {
        "status": attempt.status,
        "revision": attempt.revision,
        "expires_at": server_seconds(
            attempt.expires_at
        ),
        "server_now": server_seconds(
            timezone.now()
        ),
        "auto_submitted": attempt.auto_submitted,
        "answer": attempt.submission.text_content,
        "delta": attempt.rich_delta,
    }

@login_required
@require_http_methods(["GET", "POST"])
def configure(request, assignment_pk):

    assignment = get_object_or_404(
        Assignment,
        pk=assignment_pk,
    )

    if (
        not is_teacher(request.user)
        or assignment.created_by_id != request.user.pk
    ):
        raise PermissionDenied(
            "Only the assignment teacher can "
            "configure timed writing."
        )

    config = TimedWritingConfig.objects.filter(
        assignment=assignment
    ).first()

    form = TimedWritingConfigForm(
        request.POST or None,
        instance=config,
    )

    if (
        request.method == "POST"
        and form.is_valid()
    ):

        has_submissions = (
            Submission.objects.filter(
                assignment=assignment
            ).exists()
        )

        enabling_after_regular_submissions = (
            config is not None
            and not config.is_enabled
            and form.cleaned_data["is_enabled"]
        )

        if (
            has_submissions
            and (
                config is None
                or enabling_after_regular_submissions
            )
        ):
            form.add_error(
                None,
                "Cannot enable timed writing "
                "after submissions exist.",
            )

        else:

            configured = form.save(
                commit=False
            )

            configured.assignment = assignment

            try:
                configured.full_clean()

            except ValidationError as exc:
                form.add_error(
                    None,
                    "; ".join(exc.messages),
                )

            else:
                configured.save()

                messages.success(
                    request,
                    "Timed writing settings saved.",
                )

                return redirect(
                    "assignments:detail",
                    pk=assignment.pk,
                )

    return render(
        request,
        "timed_writing/configure.html",
        {
            "assignment": assignment,
            "form": form,
            "has_attempts": bool(
                config and config.attempts.exists()
            ),
        },
    )


@login_required
@never_cache
@require_GET
def editor(request, assignment_pk):

    assignment = get_object_or_404(
        Assignment,
        pk=assignment_pk,
    )

    enforce_student(
        request.user,
        assignment,
    )

    config = enforce_config(assignment)

    attempt = (
        TimedWritingAttempt.objects.filter(
            config=config,
            student=request.user,
        ).first()
    )

    if attempt:
        attempt = read_attempt(
            assignment.pk,
            request.user,
        )

    existing = Submission.objects.filter(
        assignment=assignment,
        student=request.user,
    ).first()

    return render(
        request,
        "timed_writing/editor.html",
        {
            "assignment": assignment,
            "config": config,
            "attempt": attempt,
            "existing": existing,
            "server_now": server_seconds(
                timezone.now()
            ),
            "expiry_seconds": (
                server_seconds(attempt.expires_at)
                if attempt
                else None
            ),
        },
    )


@login_required
@require_POST
def start(request, assignment_pk):

    assignment = get_object_or_404(
        Assignment,
        pk=assignment_pk,
    )

    attempt = begin(
        assignment.pk,
        request.user,
    )

    if (
        attempt.status
        == TimedWritingAttempt.Status.ACTIVE
    ):
        messages.success(
            request,
            "Writing attempt started. "
            "The server timer is running.",
        )

    return redirect(
        "timed_writing:editor",
        assignment_pk=assignment_pk,
    )


@login_required
@never_cache
@require_GET
def status(request, assignment_pk):

    assignment = get_object_or_404(
        Assignment,
        pk=assignment_pk,
    )

    enforce_student(
        request.user,
        assignment,
    )

    attempt = get_object_or_404(
        TimedWritingAttempt,
        config__assignment=assignment,
        student=request.user,
    )

    attempt = read_attempt(
        assignment.pk,
        request.user,
    )

    return JsonResponse(
        payload(attempt)
    )


@login_required
@never_cache
@require_POST
def save(request, assignment_pk):

    assignment = get_object_or_404(
        Assignment,
        pk=assignment_pk,
    )

    enforce_student(
        request.user,
        assignment,
    )

    if len(request.body) > 500_000:
        return JsonResponse(
            {"error": "Request too large"},
            status=413,
        )

    try:

        data = json.loads(
            request.body.decode("utf-8")
        )

        if not isinstance(data, dict):
            raise ValueError()

        answer = data["answer"]
        revision = data["revision"]

        action = data.get(
            "action",
            "save",
        )

        if (
            type(revision) is not int
            or revision < 0
            or action not in {"save", "finish"}
        ):
            raise ValueError()

        attempt, outcome = write_answer(
            assignment.pk,
            request.user,
            answer,
            revision,
            finalize=(action == "finish"),
            delta=data.get("delta"),
        )

    except (
        ValueError,
        TypeError,
        KeyError,
        UnicodeDecodeError,
    ):
        return JsonResponse(
            {"error": "Invalid request"},
            status=400,
        )

    except TimedWritingAttempt.DoesNotExist:
        return JsonResponse(
            {"error": "Start writing first"},
            status=404,
        )

    except ValidationError as exc:
        return JsonResponse(
            {
                "error": "; ".join(
                    exc.messages
                )
            },
            status=400,
        )

    response = payload(attempt)

    if outcome == "conflict":

        response["error"] = (
            "Answer was changed in another tab. "
            "Reload carefully before editing."
        )

        return JsonResponse(
            response,
            status=409,
        )

    if outcome == "closed":

        response["error"] = (
            "Attempt is already finished "
            "or expired."
        )

        return JsonResponse(
            response,
            status=409,
        )

    return JsonResponse(response)