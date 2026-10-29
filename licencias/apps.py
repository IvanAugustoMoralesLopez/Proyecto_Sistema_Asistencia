from django.apps import AppConfig


class LicenciasConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'licencias'
    # Sin ready(): la bitácora (RF-20) la escriben los triggers de la base en la
    # tabla `auditoria`, así que ya no se usa licencias/signals.py.
