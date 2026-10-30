from django.apps import AppConfig


class LicenciasConfig(AppConfig): # El nombre de la clase puede variar según tu app
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'licencias' # Asegurate de que coincida con el nombre de tu carpeta

    def ready(self):
        import licencias.signals
