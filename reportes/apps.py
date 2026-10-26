from django.apps import AppConfig


class ReportesConfig(AppConfig):
    name = 'reportes'

    def ready(self):
        from . import signals  # noqa: F401
