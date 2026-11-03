"""AssignHub monitoring policies, sessions, browser and AI signals."""
from django.conf import settings
from django.db import models
from django.utils import timezone


class ProctoringPolicy(models.Model):
    quiz = models.OneToOneField('quizzes.Quiz', on_delete=models.CASCADE, related_name='proctoring_policy')
    enabled = models.BooleanField(default=False)
    require_camera = models.BooleanField(default=True)
    log_browser_events = models.BooleanField(default=True)
    # All AI options are OFF by default for backwards compatibility.
    ai_enabled = models.BooleanField(default=False)
    detect_multiple_faces = models.BooleanField(default=True)
    detect_face_absence = models.BooleanField(default=True)
    detect_head_movement = models.BooleanField(default=True)
    detect_phone = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Proctoring policy for {self.quiz_id}'


class MonitoringSession(models.Model):
    attempt = models.OneToOneField('quizzes.QuizAttempt', on_delete=models.CASCADE, related_name='monitoring_session')
    consent_at = models.DateTimeField()
    camera_check_claimed = models.BooleanField(default=False)
    started_at = models.DateTimeField(default=timezone.now)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'Monitoring for attempt {self.attempt_id}'


class MonitoringEvent(models.Model):
    class Source(models.TextChoices):
        BROWSER = 'BROWSER', 'Browser / device'
        AI = 'AI', 'Local AI model'

    class Kind(models.TextChoices):
        TAB_HIDDEN = 'TAB_HIDDEN', 'Exam tab hidden'
        WINDOW_BLUR = 'WINDOW_BLUR', 'Window focus lost'
        FULLSCREEN_EXIT = 'FULLSCREEN_EXIT', 'Fullscreen exited'
        CAMERA_LOST = 'CAMERA_LOST', 'Camera unavailable'
        CAMERA_RESTORED = 'CAMERA_RESTORED', 'Camera restored'
        MONITOR_ERROR = 'MONITOR_ERROR', 'Monitoring interrupted'
        NO_FACE = 'NO_FACE', 'No face visible (model signal)'
        MULTIPLE_FACES = 'MULTIPLE_FACES', 'Multiple faces detected (model signal)'
        HEAD_TURNED = 'HEAD_TURNED', 'Sustained head-angle change (heuristic)'
        PHONE_VISIBLE = 'PHONE_VISIBLE', 'Possible mobile phone visible (model signal)'

    class Review(models.TextChoices):
        PENDING = 'PENDING', 'Needs review'
        REVIEWED = 'REVIEWED', 'Reviewed'
        DISMISSED = 'DISMISSED', 'Dismissed'

    session = models.ForeignKey(MonitoringSession, on_delete=models.CASCADE, related_name='events')
    kind = models.CharField(max_length=24, choices=Kind.choices)
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.BROWSER)
    confidence = models.FloatField(null=True, blank=True)
    duration_seconds = models.PositiveSmallIntegerField(default=0)
    observed_faces = models.PositiveSmallIntegerField(null=True, blank=True)
    review_status = models.CharField(max_length=12, choices=Review.choices, default=Review.PENDING)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='reviewed_exam_events')

    class Meta:
        ordering = ['-created_at', '-pk']
        indexes = [models.Index(fields=['session', '-created_at'], name='ah_proctor_events_idx')]

    def __str__(self):
        return f'{self.session_id}: {self.kind}'
