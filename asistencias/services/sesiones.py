"""
Concurrencia y sesión de edición.

Solo dos operadores pueden tener una sesión de edición activa a la vez
(MAX_OPERADORES). `ControlConcurrencia` es la fila que se bloquea con
`select_for_update()` antes de contar o tocar las sesiones activas, para
que dos peticiones simultáneas no se pisen.
"""

from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from ..models import ControlConcurrencia, SesionEdicion


MAX_OPERADORES = 2
MINUTOS_EXPIRACION_SESION = 15


def _obtener_control_bloqueado():
    """
    Obtiene el registro coordinador dentro de una transacción.
    Todas las operaciones que cambien las sesiones activas deben
    bloquear esta misma fila antes de contar o insertar sesiones.
    """
    try:
        return ControlConcurrencia.objects.select_for_update().get(pk=1)
    except ControlConcurrencia.DoesNotExist as exc:
        raise RuntimeError(
            "No existe el control de concurrencia. "
            "Ejecutá las migraciones y verificá las señales."
        ) from exc


@transaction.atomic
def adquirir_sesion_edicion(usuario, token):
    """
    Registra una sesión de trabajo para un usuario autenticado.
    El token debe conservarse en la sesión de Django.
    """
    if not usuario.is_authenticated:
        raise PermissionDenied("Debés iniciar sesión.")

    _obtener_control_bloqueado()
    ahora = timezone.now()

    SesionEdicion.objects.filter(
        activa=True,
        expira_en__lte=ahora,
    ).update(activa=False)

    sesion_existente = SesionEdicion.objects.filter(
        token=token,
        activa=True,
    ).first()

    if sesion_existente:
        if sesion_existente.usuario_id != usuario.pk:
            raise PermissionDenied(
                "El token de edición pertenece a otro usuario."
            )

        sesion_existente.heartbeat_en = ahora
        sesion_existente.expira_en = (
            ahora + timedelta(minutes=MINUTOS_EXPIRACION_SESION)
        )
        sesion_existente.save(
            update_fields=["heartbeat_en", "expira_en"]
        )
        return sesion_existente

    cantidad = SesionEdicion.objects.filter(
        activa=True,
        expira_en__gt=ahora,
    ).count()

    if cantidad >= MAX_OPERADORES:
        raise ValidationError(
            "Ya hay dos operadores activos en asistencia. "
            "Intentá nuevamente más tarde."
        )

    return SesionEdicion.objects.create(
        usuario=usuario,
        token=token,
        heartbeat_en=ahora,
        expira_en=ahora + timedelta(
            minutes=MINUTOS_EXPIRACION_SESION
        ),
        activa=True,
    )


@transaction.atomic
def renovar_sesion_edicion(usuario, token):
    """
    Renueva la sesión activa de un operador.
    Se llama desde una petición autenticada, no desde un temporizador
    sin autenticación.
    """
    _obtener_control_bloqueado()

    ahora = timezone.now()

    try:
        sesion = SesionEdicion.objects.select_for_update().get(
            token=token,
            usuario=usuario,
            activa=True,
            expira_en__gt=ahora,
        )
    except SesionEdicion.DoesNotExist as exc:
        raise ValidationError(
            "La sesión de edición expiró. Volvé a ingresar."
        ) from exc

    sesion.heartbeat_en = ahora
    sesion.expira_en = ahora + timedelta(
        minutes=MINUTOS_EXPIRACION_SESION
    )
    sesion.save(update_fields=["heartbeat_en", "expira_en"])

    return sesion


@transaction.atomic
def liberar_sesion_edicion(usuario, token):
    _obtener_control_bloqueado()

    SesionEdicion.objects.filter(
        usuario=usuario,
        token=token,
        activa=True,
    ).update(activa=False)


def _validar_sesion_edicion(usuario, token):
    if not token:
        raise PermissionDenied(
            "No existe una sesión de edición activa."
        )

    ahora = timezone.now()

    try:
        return SesionEdicion.objects.get(
            usuario=usuario,
            token=token,
            activa=True,
            expira_en__gt=ahora,
        )
    except SesionEdicion.DoesNotExist as exc:
        raise PermissionDenied(
            "La sesión de edición expiró. Volvé a ingresar."
        ) from exc
