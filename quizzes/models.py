from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Quiz(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        PUBLISHED = 'PUBLISHED', 'Published'
        CLOSED = 'CLOSED', 'Closed'

    course_offering = models.ForeignKey('courses.CourseOffering', on_delete=models.PROTECT, related_name='quizzes')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='authored_quizzes')
    title = models.CharField(max_length=180)
    instructions = models.TextField(blank=True)
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    duration_minutes = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(240)])
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    show_results = models.BooleanField(default=True, help_text='Allow students to see scores and correct answers after submission.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-pk']

    def clean(self):
        super().clean()
        errors = {}
        if self.opens_at and self.closes_at and self.opens_at >= self.closes_at:
            errors['closes_at'] = 'Closing time must be after opening time.'
        if self.course_offering_id and self.created_by_id:
            if self.course_offering.teacher_id != self.created_by_id:
                errors['course_offering'] = 'Quiz must belong to the assigned course teacher.'
            if self.status == self.Status.PUBLISHED and not self.course_offering.is_active:
                errors['course_offering'] = 'Cannot publish into an inactive course offering.'
        if errors:
            raise ValidationError(errors)

    @property
    def total_marks(self):
        return sum(q.points for q in self.questions.all())

    @property
    def is_open(self):
        now = timezone.now()
        return self.status == self.Status.PUBLISHED and self.opens_at <= now < self.closes_at

    def __str__(self):
        return self.title


class QuizQuestion(models.Model):
    class Choice(models.TextChoices):
        A = 'A', 'A'
        B = 'B', 'B'
        C = 'C', 'C'
        D = 'D', 'D'

    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='questions')
    text = models.TextField(max_length=2000)
    option_a = models.CharField(max_length=500)
    option_b = models.CharField(max_length=500)
    option_c = models.CharField(max_length=500)
    option_d = models.CharField(max_length=500)
    correct_choice = models.CharField(max_length=1, choices=Choice.choices)
    points = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(100)])
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'pk']

    def __str__(self):
        return f'{self.quiz.title}: {self.text[:50]}'


class QuizAttempt(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = 'IN_PROGRESS', 'In progress'
        SUBMITTED = 'SUBMITTED', 'Submitted'
        AUTO_SUBMITTED = 'AUTO_SUBMITTED', 'Auto-submitted'

    quiz = models.ForeignKey(Quiz, on_delete=models.PROTECT, related_name='attempts')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='quiz_attempts')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_PROGRESS)
    started_at = models.DateTimeField(default=timezone.now, editable=False)
    expires_at = models.DateTimeField(editable=False)
    submitted_at = models.DateTimeField(null=True, blank=True)
    earned_marks = models.PositiveIntegerField(null=True, blank=True)
    total_marks = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at', '-pk']
        constraints = [models.UniqueConstraint(fields=['quiz', 'student'], name='ah_quiz_one_attempt_student')]
        indexes = [models.Index(fields=['status', 'expires_at'], name='ah_quiz_expiry_idx')]

    def save(self, *args, **kwargs):
        if self._state.adding and not self.expires_at:
            self.expires_at = min(self.started_at + timedelta(minutes=self.quiz.duration_minutes), self.quiz.closes_at)
        super().save(*args, **kwargs)

    @property
    def is_finished(self):
        return self.status != self.Status.IN_PROGRESS

    def __str__(self):
        return f'{self.quiz_id}: {self.student_id} ({self.status})'


class QuizAnswer(models.Model):
    attempt = models.ForeignKey(QuizAttempt, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(QuizQuestion, on_delete=models.PROTECT, related_name='student_answers')
    selected_choice = models.CharField(max_length=1, choices=QuizQuestion.Choice.choices)
    saved_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['attempt', 'question'], name='ah_quiz_one_answer_question')]

    def clean(self):
        super().clean()
        if self.attempt_id and self.question_id and self.attempt.quiz_id != self.question.quiz_id:
            raise ValidationError('Question is not part of this quiz.')
