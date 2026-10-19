
from django.db.models.signals import post_migrate
from django.dispatch import receiver


@receiver(post_migrate)
def crear_control_concurrencia(sender, **kwargs):
    """
    Crea el registro de control de concurrencia después
    de aplicar las migraciones de la aplicación.
    """
    if sender.label != "asistencias":
        return

    # Importación local para evitar problemas de carga de modelos.
    from .models import ControlConcurrencia

    ControlConcurrencia.objects.get_or_create(pk=1)
