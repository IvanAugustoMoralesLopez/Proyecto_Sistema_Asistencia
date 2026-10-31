"""
Cierre y reapertura de jornadas (RN-06) y de períodos mensuales.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from ..models import CierreDiario, CierreMensual, EventoAsistencia, RegistroAsistencia
from .reglas import MOTIVO_MINIMO, _exigir_permiso, _validar_periodo_abierto, motivo_dia_no_laborable
from .sesiones import _obtener_control_bloqueado, _validar_sesion_edicion


@transaction.atomic
def cerrar_dia(*, usuario, token, fecha):
    """
    Cierra la jornada (RN-06). Desde ese momento modificar sus registros
    requiere el permiso `modificar_jornada_cerrada` y un motivo.
    """
    _exigir_permiso(
        usuario,
        "asistencias.cerrar_jornada",
        "No tenés permiso para cerrar la jornada.",
    )
    _validar_sesion_edicion(usuario, token)

    if fecha > timezone.localdate():
        raise ValidationError("No se puede cerrar una jornada futura.")

    motivo = motivo_dia_no_laborable(fecha)

    if motivo:
        raise ValidationError(f"{motivo}: no hay jornada para cerrar.")

    _validar_periodo_abierto(fecha)

    cierre, creado = CierreDiario.objects.get_or_create(
        fecha=fecha,
        defaults={"cerrado_por": usuario},
    )

    if not creado:
        raise ValidationError("La jornada ya está cerrada.")

    EventoAsistencia.objects.create(
        cierre_diario=cierre,
        usuario=usuario,
        accion=EventoAsistencia.Accion.CERRAR_DIA,
        despues={
            "fecha": fecha.isoformat(),
            "registros": RegistroAsistencia.objects.filter(
                fecha=fecha
            ).count(),
        },
    )

    return cierre


@transaction.atomic
def cerrar_mes(*, usuario, anio, mes, token):
    _exigir_permiso(
        usuario,
        "asistencias.cerrar_periodo",
        "No tenés permiso para cerrar períodos.",
    )
    _validar_sesion_edicion(usuario, token)
    _obtener_control_bloqueado()

    if not 1 <= mes <= 12:
        raise ValidationError("El mes debe estar entre 1 y 12.")

    cierre, _ = CierreMensual.objects.select_for_update().get_or_create(
        anio=anio,
        mes=mes,
    )

    if cierre.estado == CierreMensual.Estado.CERRADO:
        raise ValidationError("El período ya está cerrado.")

    pendientes = RegistroAsistencia.objects.filter(
        fecha__year=anio,
        fecha__month=mes,
        estado_registro=RegistroAsistencia.Estado.BORRADOR,
    ).exists()

    if pendientes:
        raise ValidationError(
            "No se puede cerrar: hay registros sin validar."
        )

    cierre.estado = CierreMensual.Estado.CERRADO
    cierre.cerrado_por = usuario
    cierre.cerrado_en = timezone.now()
    cierre.reabierto_por = None
    cierre.reabierto_en = None
    cierre.motivo_reapertura = ""
    cierre.version += 1
    cierre.save()

    EventoAsistencia.objects.create(
        cierre=cierre,
        usuario=usuario,
        accion=EventoAsistencia.Accion.CERRAR,
        despues={
            "anio": anio,
            "mes": mes,
            "estado": cierre.estado,
            "version": cierre.version,
        },
    )

    return cierre


@transaction.atomic
def reabrir_mes(*, usuario, anio, mes, motivo, token):
    if not usuario.has_perm("asistencias.change_cierremensual"):
        raise PermissionDenied(
            "No tenés permiso para reabrir períodos."
        )

    _validar_sesion_edicion(usuario, token)
    _obtener_control_bloqueado()

    motivo = motivo.strip()

    if len(motivo) < MOTIVO_MINIMO:
        raise ValidationError(
            "El motivo de reapertura debe tener al menos "
            f"{MOTIVO_MINIMO} caracteres."
        )

    cierre = CierreMensual.objects.select_for_update().get(
        anio=anio,
        mes=mes,
    )

    if cierre.estado != CierreMensual.Estado.CERRADO:
        raise ValidationError("El período no está cerrado.")

    antes = {
        "anio": cierre.anio,
        "mes": cierre.mes,
        "estado": cierre.estado,
        "version": cierre.version,
    }

    cierre.estado = CierreMensual.Estado.ABIERTO
    cierre.reabierto_por = usuario
    cierre.reabierto_en = timezone.now()
    cierre.motivo_reapertura = motivo
    cierre.version += 1
    cierre.save()

    EventoAsistencia.objects.create(
        cierre=cierre,
        usuario=usuario,
        accion=EventoAsistencia.Accion.REABRIR,
        motivo=motivo,
        antes=antes,
        despues={
            "anio": cierre.anio,
            "mes": cierre.mes,
            "estado": cierre.estado,
            "version": cierre.version,
        },
    )

    return cierre
