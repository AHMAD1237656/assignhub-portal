"""Categorized teacher monitoring and consent-led, browser-side instrumentation."""
from datetime import timedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from assignments.permissions import is_admin, is_teacher
from courses.models import CourseOffering
from quizzes.models import Quiz, QuizAttempt
from quizzes.services import begin, student_can_see
from quizzes.views import accessible_offerings, _class_name
from .forms import PolicyForm
from .models import MonitoringEvent, MonitoringSession, ProctoringPolicy
from .services import active_student_session, can_review, is_proctored, open_session, require_review


def _manager_offerings(user):
    if not (is_admin(user) or is_teacher(user)):
        raise PermissionDenied('Monitoring dashboards are for teachers and administrators only.')
    return accessible_offerings(user)


@login_required
@never_cache
@require_GET
def classes(request):
    qs = _manager_offerings(request.user).order_by('-academic_year', 'term', 'section__code', 'course__code')
    groups = {}
    term_q = request.GET.get('q', '').strip()[:80].casefold()
    for offering in qs:
        label = _class_name(offering)
        term_label = f'{offering.get_term_display()} {offering.academic_year}'
        if term_q and term_q not in f'{label} {term_label} {offering.course.code} {offering.course.title}'.casefold():
            continue
        key = (offering.section_id, offering.academic_year, offering.term)
        if key not in groups:
            groups[key] = {'section_id': offering.section_id, 'year': offering.academic_year,
                           'term': offering.term, 'label': label, 'subtitle': term_label, 'courses': 0}
        groups[key]['courses'] += 1
    return render(request, 'quiz_proctoring/classes.html', {'classes': list(groups.values()), 'search': term_q})


@login_required
@never_cache
@require_GET
def class_courses(request, section_pk, year, term):
    offerings = list(_manager_offerings(request.user).filter(
        section_id=section_pk, academic_year=year, term=term,
    ).order_by('course__code'))
    if not offerings:
        raise PermissionDenied('Class not allocated to this account.')
    counts = dict(Quiz.objects.filter(course_offering__in=offerings)
                  .values('course_offering_id').annotate(n=Count('pk')).values_list('course_offering_id', 'n'))
    rows = [{'offering': obj, 'quiz_count': counts.get(obj.pk, 0)} for obj in offerings]
    return render(request, 'quiz_proctoring/courses.html', {
        'class_label': _class_name(offerings[0]), 'class_term': f'{offerings[0].get_term_display()} {year}', 'courses': rows,
    })


@login_required
@never_cache
@require_GET
def course_quizzes(request, offering_pk):
    offering = get_object_or_404(_manager_offerings(request.user), pk=offering_pk)
    quiz_qs = Quiz.objects.filter(course_offering=offering)
    if is_teacher(request.user):
        quiz_qs = quiz_qs.filter(created_by=request.user)
    rows = quiz_qs.select_related('proctoring_policy').order_by('-created_at', '-pk')[:200]
    return render(request, 'quiz_proctoring/quizzes.html', {
        'offering': offering, 'class_label': _class_name(offering), 'quizzes': rows,
    })


@login_required
@never_cache
@require_GET
def quiz_monitoring(request, quiz_pk):
    quiz = get_object_or_404(Quiz.objects.select_related('course_offering__course', 'course_offering__section'), pk=quiz_pk)
    require_review(request.user, quiz)
    attempts = list(QuizAttempt.objects.filter(quiz=quiz).select_related('student', 'monitoring_session')
                    .annotate(event_count=Count('monitoring_session__events')).order_by('student__username')[:400])
    policy = ProctoringPolicy.objects.filter(quiz=quiz).first()
    return render(request, 'quiz_proctoring/quiz.html', {
        'quiz': quiz, 'attempts': attempts, 'policy': policy,
        'class_label': _class_name(quiz.course_offering),
        'can_edit_policy': is_teacher(request.user) and quiz.created_by_id == request.user.pk and quiz.status == Quiz.Status.DRAFT and not quiz.attempts.exists(),
    })


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def settings(request, quiz_pk):
    quiz = get_object_or_404(Quiz, pk=quiz_pk)
    if not (is_teacher(request.user) and quiz.created_by_id == request.user.pk and quiz.course_offering.teacher_id == request.user.pk):
        raise PermissionDenied('Only the assigned teacher may configure monitoring.')
    if quiz.status != Quiz.Status.DRAFT or quiz.attempts.exists():
        raise PermissionDenied('Monitoring settings are locked after publishing or attempts.')
    policy = ProctoringPolicy.objects.filter(quiz=quiz).first()
    form = PolicyForm(request.POST or None, instance=policy)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            locked = Quiz.objects.select_for_update().get(pk=quiz.pk)
            if locked.status != Quiz.Status.DRAFT or locked.attempts.exists():
                raise PermissionDenied('Quiz already published or started.')
            updated = form.save(commit=False)
            updated.quiz = locked
            updated.save()
        messages.success(request, 'Exam monitoring settings saved.')
        return redirect('quizzes:detail', pk=quiz.pk)
    return render(request, 'quiz_proctoring/settings.html', {'quiz': quiz, 'form': form})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def device_check(request, quiz_pk):
    quiz = get_object_or_404(Quiz, pk=quiz_pk)
    if not student_can_see(request.user, quiz):
        raise PermissionDenied('Only actively enrolled students can take this quiz.')
    existing = QuizAttempt.objects.filter(quiz=quiz, student=request.user).first()
    if existing:
        return redirect('quizzes:result' if existing.is_finished else 'quizzes:take', pk=quiz.pk)
    policy = ProctoringPolicy.objects.filter(quiz=quiz, enabled=True).first()
    if policy is None:
        return redirect('quizzes:detail', pk=quiz.pk)
    if not quiz.is_open:
        messages.error(request, 'This quiz is not currently open.')
        return redirect('quizzes:detail', pk=quiz.pk)
    if request.method == 'POST':
        consent = request.POST.get('consent') == 'yes'
        camera_checked = request.POST.get('camera_checked') == 'yes'
        if not consent or (policy.require_camera and not camera_checked):
            messages.error(request, 'Consent and required device check must be completed before starting.')
        else:
            # Client-side webcam confirmation is advisory, not secure hardware attestation.
            with transaction.atomic():
                attempt = begin(quiz.pk, request.user)
                open_session(attempt, camera_check_claimed=camera_checked)
            return redirect('quizzes:result' if attempt.is_finished else 'quizzes:take', pk=quiz.pk)
    return render(request, 'quiz_proctoring/device_check.html', {
        'quiz': quiz, 'policy': policy, 'camera_required': policy.require_camera,
    })


@login_required
@require_POST
def heartbeat(request, quiz_pk):
    quiz = get_object_or_404(Quiz, pk=quiz_pk)
    session = active_student_session(request.user, quiz)
    now = timezone.now()
    MonitoringSession.objects.filter(pk=session.pk).update(last_heartbeat_at=now)
    return JsonResponse({'ok': True, 'server_time': now.isoformat()})


@login_required
@require_POST
def record_event(request, quiz_pk):
    quiz = get_object_or_404(Quiz, pk=quiz_pk)
    session = active_student_session(request.user, quiz)
    policy = ProctoringPolicy.objects.filter(quiz=quiz, enabled=True).first()
    if not policy or not policy.log_browser_events:
        return JsonResponse({'ok': False, 'error': 'Event logging disabled'}, status=403)
    kind = request.POST.get('kind', '')
    if kind not in MonitoringEvent.Kind.values:
        return JsonResponse({'ok': False, 'error': 'Invalid event'}, status=400)
    now = timezone.now()
    # Do not let a noisy client flood the incident table: at most one per kind per 10 seconds.
    with transaction.atomic():
        locked = MonitoringSession.objects.select_for_update().get(pk=session.pk)
        previous = MonitoringEvent.objects.filter(session=locked, kind=kind, created_at__gte=now - timedelta(seconds=10)).exists()
        if not previous:
            MonitoringEvent.objects.create(session=locked, kind=kind, created_at=now)
        MonitoringSession.objects.filter(pk=locked.pk).update(last_heartbeat_at=now)
    return JsonResponse({'ok': True, 'recorded': not previous})


@login_required
@never_cache
@require_GET
def attempt_events(request, attempt_pk):
    attempt = get_object_or_404(QuizAttempt.objects.select_related('quiz__course_offering__course', 'student'), pk=attempt_pk)
    require_review(request.user, attempt.quiz)
    session = MonitoringSession.objects.filter(attempt=attempt).first()
    events = list(MonitoringEvent.objects.filter(session=session).select_related('reviewed_by')[:300]) if session else []
    now = timezone.now()
    stale = bool(session and attempt.status == QuizAttempt.Status.IN_PROGRESS and
                 (session.last_heartbeat_at is None or session.last_heartbeat_at < now - timedelta(seconds=75)))
    return render(request, 'quiz_proctoring/attempt.html', {
        'attempt': attempt, 'session': session, 'events': events, 'stale': stale,
        'can_review_events': is_teacher(request.user) and attempt.quiz.created_by_id == request.user.pk,
    })


@login_required
@require_POST
def review_event(request, event_pk):
    event = get_object_or_404(MonitoringEvent.objects.select_related('session__attempt__quiz'), pk=event_pk)
    quiz = event.session.attempt.quiz
    if not (is_teacher(request.user) and quiz.created_by_id == request.user.pk and quiz.course_offering.teacher_id == request.user.pk):
        raise PermissionDenied('Only the assigned teacher may review events.')
    status = request.POST.get('decision')
    if status not in [MonitoringEvent.Review.REVIEWED, MonitoringEvent.Review.DISMISSED]:
        return JsonResponse({'error': 'Invalid decision'}, status=400)
    event.review_status = status
    event.reviewed_at = timezone.now()
    event.reviewed_by = request.user
    event.save(update_fields=['review_status', 'reviewed_at', 'reviewed_by'])
    messages.success(request, 'Monitoring event review updated.')
    return redirect('quiz_proctoring:attempt_events', attempt_pk=event.session.attempt_id)
