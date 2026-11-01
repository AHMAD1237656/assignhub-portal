from django.apps import AppConfig


class AssignmentsConfig(AppConfig):
    name = 'assignments'

    def ready(self):
        from . import signals  # noqa: F401
