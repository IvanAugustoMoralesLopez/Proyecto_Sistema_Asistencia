
from django.contrib.auth.signals import user_logged_out
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.models.signals import post_migrate
from django.dispatch import receiver

TABLA_CONTROL = "asistencia_control_concurrencia"


@receiver(post_migrate)
def crear_control_concurrencia(sender, **kwargs):
    """
    Crea el registro de control de concurrencia después
    de aplicar las migraciones de la aplicación.
    """
    if sender.label != "asistencias":
        return

    using = kwargs.get("using", DEFAULT_DB_ALIAS)

    # post_migrate también se emite al migrar solo otra app o una versión
    # intermedia de esta, cuando la tabla todavía no existe.
    if TABLA_CONTROL not in connections[using].introspection.table_names():
        return

    # Importación local para evitar problemas de carga de modelos.
    from .models import ControlConcurrencia

    ControlConcurrencia.objects.using(using).get_or_create(pk=1)


@receiver(user_logged_out)
def liberar_sesion_de_edicion(sender, request, user, **kwargs):
    """
    Al cerrar sesión se libera el lugar de edición. Si no, queda ocupado
    hasta que vence (15 minutos) y puede dejar afuera a otro operador, ya
    que solo dos pueden editar a la vez.

    Es una actualización directa y no el servicio: cerrar sesión nunca debe
    fallar por esto.
    """
    token = request.session.get("asistencia_token") if request else None

    if user is None or not token:
        return

    # Importación local para evitar problemas de carga de modelos.
    from .models import SesionEdicion

    SesionEdicion.objects.filter(
        usuario=user,
        token=token,
        activa=True,
    ).update(activa=False)
