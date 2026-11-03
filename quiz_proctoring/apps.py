from django.apps import AppConfig


class QuizProctoringConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'quiz_proctoring'
    verbose_name = 'AssignHub Exam Monitoring'

    def ready(self):
        from . import signals  # noqa: F401
