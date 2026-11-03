from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from assignments.permissions import is_admin, is_student, is_teacher
from courses.models import CourseEnrollment, CourseOffering
from .forms import QuestionForm, QuizForm
from .models import Quiz, QuizAnswer, QuizAttempt, QuizQuestion
from .services import begin, finish, refresh, save_choice, student_can_see
from quiz_proctoring.services import is_proctored


def teacher_owns(user, quiz):
    return is_teacher(user) and quiz.created_by_id == user.pk and quiz.course_offering.teacher_id == user.pk


def manager_allowed(user, quiz):
    return teacher_owns(user, quiz) or is_admin(user)


def editable(user, quiz):
    if not teacher_owns(user, quiz):
        raise PermissionDenied('Only the owning teacher may edit this quiz.')
    if quiz.status != Quiz.Status.DRAFT or quiz.attempts.exists():
        raise PermissionDenied('Published quizzes or quizzes with attempts cannot be edited.')


def accessible_offerings(user):
    """One canonical role-scoped queryset. Never trust class/course URL parameters."""
    offerings = CourseOffering.objects.select_related(
        'course', 'section', 'section__semester',
        'section__semester__program', 'teacher',
    ).filter(
        is_active=True, course__is_active=True, section__is_active=True,
    )
    if is_admin(user):
        return offerings
    if is_teacher(user):
        return offerings.filter(teacher=user)
    if is_student(user):
        return offerings.filter(
            enrollments__student=user,
            enrollments__status=CourseEnrollment.Status.ACTIVE,
        ).distinct()
    raise PermissionDenied('Quiz Center access is not allowed for this account.')


def _visible_quizzes(user, offerings):
    quizzes = Quiz.objects.filter(course_offering__in=offerings)
    if is_teacher(user):
        return quizzes.filter(created_by=user)
    if is_student(user):
        return quizzes.filter(status__in=[Quiz.Status.PUBLISHED, Quiz.Status.CLOSED])
    return quizzes


def _class_name(offering):
    section = offering.section
    program = section.semester.program
    return f'{program.code} · Semester {section.semester.number} · Section {section.code}'


@login_required
@never_cache
@require_GET
def quiz_list(request):
    """Class-first landing page for all roles. Teacher sees only allocated classes."""
    qs = accessible_offerings(request.user).order_by(
        '-academic_year', 'term', 'section__semester__program__code',
        'section__semester__number', 'section__code', 'course__code',
    )
    keyword = request.GET.get('q', '').strip()[:80]
    groups = {}
    for offering in qs:
        label = _class_name(offering)
        subtitle = f'{offering.get_term_display()} · {offering.academic_year}'
        if keyword and keyword.casefold() not in (label + ' ' + subtitle + ' ' + offering.course.code + ' ' + offering.course.title).casefold():
            continue
        key = (offering.section_id, offering.academic_year, offering.term)
        if key not in groups:
            groups[key] = {
                'section_id': offering.section_id, 'year': offering.academic_year,
                'term': offering.term, 'label': label, 'subtitle': subtitle,
                'course_ids': set(), 'offerings': [],
            }
        groups[key]['course_ids'].add(offering.course_id)
        groups[key]['offerings'].append(offering.pk)
    all_offering_ids = [pk for group in groups.values() for pk in group['offerings']]
    quiz_counts = dict(
        _visible_quizzes(request.user, accessible_offerings(request.user))
        .filter(course_offering_id__in=all_offering_ids)
        .values('course_offering_id').annotate(n=Count('pk'))
        .values_list('course_offering_id', 'n')
    )
    rows = []
    for group in groups.values():
        group['course_count'] = len(group.pop('course_ids'))
        group['quiz_count'] = sum(quiz_counts.get(pk, 0) for pk in group.pop('offerings'))
        rows.append(group)
    return render(request, 'quizzes/list.html', {
        'classes': rows, 'keyword': keyword,
        'role_label': 'Teaching classes' if is_teacher(request.user) else ('My enrolled classes' if is_student(request.user) else 'Academic classes'),
    })


@login_required
@never_cache
@require_GET
def class_courses(request, section_pk, year, term):
    """Only courses taught/enrolled in the selected section AND academic term."""
    offerings = accessible_offerings(request.user).filter(
        section_id=section_pk, academic_year=year, term=term,
    ).order_by('course__code', 'course__title')
    courses = list(offerings)
    if not courses:
        raise PermissionDenied('This class is not allocated to your account.')
    matched = _visible_quizzes(request.user, offerings).values('course_offering_id').annotate(total=Count('pk'))
    count_map = {item['course_offering_id']: item['total'] for item in matched}
    rows = [{'offering': offering, 'quiz_count': count_map.get(offering.pk, 0)} for offering in courses]
    return render(request, 'quizzes/classes.html', {
        'courses': rows, 'class_label': _class_name(courses[0]),
        'class_term': f'{courses[0].get_term_display()} · {year}',
        'is_teacher': is_teacher(request.user),
    })


@login_required
@never_cache
@require_GET
def course_quizzes(request, offering_pk):
    offering = get_object_or_404(accessible_offerings(request.user), pk=offering_pk)
    items = _visible_quizzes(request.user, accessible_offerings(request.user).filter(pk=offering.pk))
    scope = request.GET.get('status', 'all').lower()
    if scope not in {'all', 'draft', 'published', 'closed'}:
        scope = 'all'
    if scope != 'all':
        items = items.filter(status=scope.upper())
    keyword = request.GET.get('q', '').strip()[:80]
    if keyword:
        items = items.filter(title__icontains=keyword)
    items = items.order_by('-created_at', '-pk')
    return render(request, 'quizzes/course_quizzes.html', {
        'offering': offering, 'quizzes': items[:200], 'scope': scope,
        'keyword': keyword, 'can_create': is_teacher(request.user),
        'is_student': is_student(request.user),
        'class_label': _class_name(offering),
    })


@login_required
@never_cache
@require_GET
def quiz_detail(request, pk):
    quiz = get_object_or_404(Quiz.objects.select_related('course_offering__course', 'course_offering__section'), pk=pk)
    manager = manager_allowed(request.user, quiz)
    student = student_can_see(request.user, quiz)
    if not manager and not (student and quiz.status != Quiz.Status.DRAFT):
        raise PermissionDenied('Quiz not accessible.')
    attempt = QuizAttempt.objects.filter(quiz=quiz, student=request.user).first() if student else None
    if attempt and attempt.status == QuizAttempt.Status.IN_PROGRESS:
        attempt = refresh(attempt.pk, request.user)
    return render(request, 'quizzes/detail.html', {
        'quiz': quiz, 'manager': manager, 'can_edit': teacher_owns(request.user, quiz) and quiz.status == Quiz.Status.DRAFT and not quiz.attempts.exists(),
        'questions': quiz.questions.all() if manager else (), 'attempt': attempt,
        'student': student, 'can_start': student and attempt is None and quiz.is_open, 'now': timezone.now(),
        'class_label': _class_name(quiz.course_offering),
    })


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def quiz_create(request, offering_pk):
    if not is_teacher(request.user):
        raise PermissionDenied('Teacher access required.')
    offering = get_object_or_404(accessible_offerings(request.user), pk=offering_pk)
    form = QuizForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        quiz = form.save(commit=False)
        quiz.course_offering = offering   # Bound to URL, not untrusted POST data.
        quiz.created_by = request.user
        quiz.status = Quiz.Status.DRAFT
        quiz.full_clean()
        quiz.save()
        messages.success(request, 'Quiz draft created. Add questions before publishing.')
        return redirect('quizzes:detail', pk=quiz.pk)
    return render(request, 'quizzes/form.html', {
        'form': form, 'heading': 'Create quiz', 'offering': offering,
        'class_label': _class_name(offering),
    })


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def quiz_edit(request, pk):
    quiz = get_object_or_404(Quiz, pk=pk)
    editable(request.user, quiz)
    form = QuizForm(request.POST or None, instance=quiz)
    if request.method == 'POST' and form.is_valid():
        new = form.save(commit=False)
        new.full_clean()
        new.save()
        messages.success(request, 'Quiz updated.')
        return redirect('quizzes:detail', pk=quiz.pk)
    return render(request, 'quizzes/form.html', {'form': form, 'heading': 'Edit quiz', 'offering': quiz.course_offering, 'class_label': _class_name(quiz.course_offering)})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def question_add(request, pk):
    quiz = get_object_or_404(Quiz, pk=pk)
    editable(request.user, quiz)
    form = QuestionForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        question = form.save(commit=False)
        question.quiz = quiz
        question.full_clean()
        question.save()
        messages.success(request, 'Question added.')
        return redirect('quizzes:detail', pk=quiz.pk)
    return render(request, 'quizzes/form.html', {'form': form, 'heading': 'Add MCQ', 'back_quiz': quiz, 'offering': quiz.course_offering})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def question_edit(request, pk, question_pk):
    quiz = get_object_or_404(Quiz, pk=pk)
    editable(request.user, quiz)
    question = get_object_or_404(QuizQuestion, quiz=quiz, pk=question_pk)
    form = QuestionForm(request.POST or None, instance=question)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Question updated.')
        return redirect('quizzes:detail', pk=quiz.pk)
    return render(request, 'quizzes/form.html', {'form': form, 'heading': 'Edit MCQ', 'back_quiz': quiz, 'offering': quiz.course_offering})


@login_required
@require_POST
def question_delete(request, pk, question_pk):
    quiz = get_object_or_404(Quiz, pk=pk)
    editable(request.user, quiz)
    question = get_object_or_404(QuizQuestion, quiz=quiz, pk=question_pk)
    question.delete()
    messages.success(request, 'Question removed.')
    return redirect('quizzes:detail', pk=quiz.pk)


@login_required
@require_POST
def publish(request, pk):
    with transaction.atomic():
        quiz = get_object_or_404(Quiz.objects.select_for_update(), pk=pk)
        editable(request.user, quiz)
        if quiz.closes_at <= timezone.now():
            messages.error(request, 'Closing date must be in the future.')
        elif not quiz.questions.exists():
            messages.error(request, 'Add at least one question before publishing.')
        else:
            quiz.full_clean()
            quiz.status = Quiz.Status.PUBLISHED
            quiz.full_clean()
            quiz.save(update_fields=['status', 'updated_at'])
            messages.success(request, 'Quiz published for the enrolled students.')
    return redirect('quizzes:detail', pk=pk)


@login_required
@require_POST
def close(request, pk):
    with transaction.atomic():
        quiz = get_object_or_404(Quiz.objects.select_for_update(), pk=pk)
        if not teacher_owns(request.user, quiz):
            raise PermissionDenied('Only the owning teacher can close this quiz.')
        if quiz.status == Quiz.Status.PUBLISHED:
            quiz.status = Quiz.Status.CLOSED
            quiz.save(update_fields=['status', 'updated_at'])
            messages.success(request, 'Quiz closed; in-progress attempts will be automatically finalized.')
    return redirect('quizzes:detail', pk=pk)


@login_required
@require_POST
def delete_draft(request, pk):
    with transaction.atomic():
        quiz = get_object_or_404(Quiz.objects.select_for_update(), pk=pk)
        editable(request.user, quiz)
        quiz.delete()
    messages.success(request, 'Draft quiz deleted.')
    return redirect('quizzes:course_quizzes', offering_pk=quiz.course_offering_id)


@login_required
@require_POST
def release_results(request, pk):
    with transaction.atomic():
        quiz = get_object_or_404(Quiz.objects.select_for_update(), pk=pk)
        if not teacher_owns(request.user, quiz):
            raise PermissionDenied('Only the owning teacher can release results.')
        if quiz.status == Quiz.Status.DRAFT or (quiz.status == Quiz.Status.PUBLISHED and timezone.now() < quiz.closes_at):
            raise PermissionDenied('Close the quiz or wait for its deadline before releasing results.')
        quiz.show_results = True
        quiz.save(update_fields=['show_results', 'updated_at'])
    messages.success(request, 'Student quiz results are now visible.')
    return redirect('quizzes:detail', pk=pk)


@login_required
@require_POST
def start(request, pk):
    quiz = get_object_or_404(Quiz, pk=pk)
    if not student_can_see(request.user, quiz):
        raise PermissionDenied('You are not eligible for this quiz.')
    if is_proctored(quiz) and not QuizAttempt.objects.filter(quiz=quiz, student=request.user).exists():
        return redirect('quiz_proctoring:device_check', quiz_pk=quiz.pk)
    attempt = begin(pk, request.user)
    return redirect('quizzes:take' if not attempt.is_finished else 'quizzes:result', pk=pk)


@login_required
@never_cache
@require_GET
def take(request, pk):
    quiz = get_object_or_404(Quiz, pk=pk)
    if not student_can_see(request.user, quiz):
        raise PermissionDenied('Quiz not accessible.')
    attempt = get_object_or_404(QuizAttempt, quiz=quiz, student=request.user)
    attempt = refresh(attempt.pk, request.user)
    if attempt.is_finished:
        return redirect('quizzes:result', pk=pk)
    selections = dict(attempt.answers.values_list('question_id', 'selected_choice'))
    rows = [{'question': q, 'selected': selections.get(q.pk, '')} for q in quiz.questions.all()]
    return render(request, 'quizzes/take.html', {
        'quiz': quiz, 'attempt': attempt, 'rows': rows,
        'expiry_epoch': int(attempt.expires_at.timestamp()),
        'server_epoch': int(timezone.now().timestamp()),
    })


@login_required
@require_POST
def answer(request, pk):
    quiz = get_object_or_404(Quiz, pk=pk)
    if not student_can_see(request.user, quiz):
        raise PermissionDenied('Not enrolled.')
    attempt = get_object_or_404(QuizAttempt, quiz=quiz, student=request.user)
    try:
        question_pk = int(request.POST.get('question_id', ''))
        choice = request.POST.get('choice', '')
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Invalid question'}, status=400)
    try:
        attempt, saved = save_choice(attempt.pk, request.user, question_pk, choice)
    except ValidationError:
        return JsonResponse({'error': 'Invalid choice'}, status=400)
    except PermissionDenied:
        return JsonResponse({'error': 'Question not allowed'}, status=403)
    if not saved:
        return JsonResponse({'saved': False, 'finished': True, 'result_url': reverse('quizzes:result', args=[quiz.pk])}, status=409)
    return JsonResponse({'saved': True, 'finished': False, 'server_now': int(timezone.now().timestamp()), 'expires_at': int(attempt.expires_at.timestamp())})


@login_required
@require_POST
def submit(request, pk):
    quiz = get_object_or_404(Quiz, pk=pk)
    if not student_can_see(request.user, quiz):
        raise PermissionDenied('Not enrolled.')
    attempt = get_object_or_404(QuizAttempt, quiz=quiz, student=request.user)
    finish(attempt.pk, request.user)
    messages.success(request, 'Quiz submitted successfully.')
    return redirect('quizzes:result', pk=pk)


@login_required
@never_cache
@require_GET
def result(request, pk):
    quiz = get_object_or_404(Quiz, pk=pk)
    if not student_can_see(request.user, quiz):
        raise PermissionDenied('Quiz not accessible.')
    attempt = get_object_or_404(QuizAttempt, quiz=quiz, student=request.user)
    attempt = refresh(attempt.pk, request.user)
    if not attempt.is_finished:
        return redirect('quizzes:take', pk=pk)
    rows = []
    results_released = quiz.show_results and (quiz.status == Quiz.Status.CLOSED or timezone.now() >= quiz.closes_at)
    if results_released:
        answers = dict(attempt.answers.values_list('question_id', 'selected_choice'))
        rows = [{'question': q, 'selected': answers.get(q.pk, ''), 'correct': answers.get(q.pk) == q.correct_choice}
                for q in quiz.questions.all()]
    return render(request, 'quizzes/result.html', {'quiz': quiz, 'attempt': attempt, 'rows': rows, 'results_released': results_released})


@login_required
@never_cache
@require_GET
def roster(request, pk):
    quiz = get_object_or_404(Quiz, pk=pk)
    if not manager_allowed(request.user, quiz):
        raise PermissionDenied('Quiz results are private.')
    # Finalize attempts whose deadline has passed before showing marks.
    for attempt_pk in quiz.attempts.filter(status=QuizAttempt.Status.IN_PROGRESS).values_list('pk', flat=True):
        with transaction.atomic():
            attempt = QuizAttempt.objects.select_for_update().select_related('quiz').get(pk=attempt_pk)
            from .services import settle_locked
            settle_locked(attempt)
    attempts = quiz.attempts.select_related('student').order_by('student__username')[:500]
    return render(request, 'quizzes/roster.html', {'quiz': quiz, 'attempts': attempts})
