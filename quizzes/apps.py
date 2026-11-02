from django.apps import AppConfig


class QuizzesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'quizzes'
    verbose_name = 'AssignHub Quiz System'

    def ready(self):
        from . import signals  # noqa: F401
