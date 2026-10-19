from django.apps import AppConfig


class PersonalConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'personal'
    verbose_name = "Gestión de Personal"
