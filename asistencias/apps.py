
from django.apps import AppConfig


class AsistenciasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "asistencias"

    def ready(self):
        from . import signals
