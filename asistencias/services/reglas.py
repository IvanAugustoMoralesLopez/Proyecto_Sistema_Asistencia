"""
Reglas y validaciones compartidas por los comandos de asistencias.

Son funciones puras (no modifican nada por sí solas) que usan los
comandos de `registro.py`, `recepcion.py` y `cierres.py` antes de
guardar o cambiar un registro.
"""

import os
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError, PermissionDenied

from ..models import (
    CierreDiario,
    CierreMensual,
    DiaNoLaborable,
    EventoAsistencia,
    RegistroAsistencia,
    licencia_cubre_fecha,
)


MOTIVO_MINIMO = 10

# Largo de la columna donde el motivo queda en el evento: más texto que eso
# lo rechaza la base de datos con un error 500.
MOTIVO_MAXIMO = EventoAsistencia._meta.get_field("motivo").max_length


def _validar_motivo_maximo(motivo):
    if len(motivo or "") > MOTIVO_MAXIMO:
        raise ValidationError(
            f"El motivo no puede superar los {MOTIVO_MAXIMO} caracteres."
        )

# Días en los que existe obligación de marcado (lunes a viernes).
DIAS_HABILES = (0, 1, 2, 3, 4)


def _exigir_permiso(usuario, permiso, mensaje):
    if not usuario.has_perm(permiso):
        raise PermissionDenied(mensaje)


def _periodo_de_fecha(fecha):
    return CierreMensual.objects.filter(
        anio=fecha.year,
        mes=fecha.month,
    ).first()


def _validar_periodo_abierto(fecha):
    cierre = _periodo_de_fecha(fecha)

    if cierre and cierre.estado == CierreMensual.Estado.CERRADO:
        raise ValidationError(
            "El período está cerrado. Solicitá una reapertura autorizada."
        )

    return cierre


def _validar_jornada_abierta(usuario, fecha, motivo):
    """
    RN-06: modificar una jornada cerrada requiere autorización de
    Secretaría o Subsecretaría y queda justificado con un motivo.
    """
    if not CierreDiario.objects.filter(fecha=fecha).exists():
        return

    _exigir_permiso(
        usuario,
        "asistencias.modificar_jornada_cerrada",
        f"La jornada del {fecha:%d/%m/%Y} está cerrada: modificarla "
        "requiere autorización de Secretaría o Subsecretaría.",
    )

    if len(motivo.strip()) < MOTIVO_MINIMO:
        raise ValidationError(
            f"La jornada del {fecha:%d/%m/%Y} está cerrada: indicá el "
            f"motivo de la modificación (al menos {MOTIVO_MINIMO} "
            "caracteres)."
        )


def _fin_de_semana_habilitado():
    """
    Solo para pruebas manuales: con ASISTENCIA_PERMITIR_FIN_DE_SEMANA=1 en el
    entorno (por ejemplo en el .env local) los sábados y domingos se tratan
    como hábiles. Exige DEBUG, así que no se puede activar en producción.
    """
    return (
        settings.DEBUG
        and os.environ.get("ASISTENCIA_PERMITIR_FIN_DE_SEMANA") == "1"
    )


def motivo_dia_no_laborable(fecha):
    """
    Devuelve el motivo por el que la fecha no tiene obligación de marcado
    (feriado, asueto, día inhábil o fin de semana), o None si es hábil.
    """
    dia = DiaNoLaborable.objects.filter(fecha=fecha).first()

    if dia:
        texto = f"{fecha:%d/%m/%Y} es {dia.get_tipo_display().lower()}"

        if dia.descripcion:
            texto += f" ({dia.descripcion})"

        return texto

    if fecha.weekday() not in DIAS_HABILES and not _fin_de_semana_habilitado():
        return f"{fecha:%d/%m/%Y} es fin de semana"

    return None


def validar_dia_laborable(fecha):
    motivo = motivo_dia_no_laborable(fecha)

    if motivo:
        raise ValidationError(
            f"{motivo}: no corresponde registrar asistencia."
        )


def _validar_designacion_vigente(designacion, fecha):
    if not designacion.activo:
        raise ValidationError("La designación está inactiva.")

    if not designacion.persona.activa:
        raise ValidationError("La persona está inactiva.")

    if fecha < designacion.desde:
        raise ValidationError(
            "La fecha es anterior al inicio de la designación."
        )

    if designacion.hasta and fecha > designacion.hasta:
        raise ValidationError(
            "La fecha es posterior al fin de la designación."
        )


def _validar_marca_requisitos(marca, horas_inasistidas, licencia):
    """
    Aplica las reglas de la marca sobre horas y licencia (equivalentes al
    CHECK de la tabla `asistencia` del diseño de base de datos: Presente
    sin horas ni licencia, Ausente con horas, Licencia con horas y una
    licencia vinculada).
    """
    horas_inasistidas = horas_inasistidas or Decimal("0")

    if marca.requiere_horas and horas_inasistidas <= Decimal("0"):
        raise ValidationError(
            "La marca seleccionada requiere indicar horas "
            "inasistidas mayores a cero."
        )

    if not marca.requiere_horas:
        horas_inasistidas = Decimal("0")

    if marca.requiere_licencia and licencia is None:
        raise ValidationError(
            "La marca seleccionada requiere una licencia vinculada."
        )

    return horas_inasistidas


def _validar_licencia(registro):
    if not registro.licencia_id:
        return

    licencia = registro.licencia

    if licencia.designacion_id != registro.designacion_id:
        raise ValidationError(
            "La licencia no pertenece a esta designación."
        )

    if not licencia_cubre_fecha(licencia, registro.fecha):
        raise ValidationError(
            "La fecha de asistencia está fuera del período de licencia."
        )


def _datos_registro(registro):
    return {
        "designacion_id": registro.designacion_id,
        "fecha": registro.fecha.isoformat(),
        "marca": registro.marca.codigo,
        "estado_registro": registro.estado_registro,
        "horas_inasistidas": str(registro.horas_inasistidas),
        "licencia_id": registro.licencia_id,
        "observaciones": registro.observaciones,
        "estado_justificacion": registro.estado_justificacion,
        "nro_formulario": registro.nro_formulario,
        "fecha_recepcion": (
            registro.fecha_recepcion.isoformat()
            if registro.fecha_recepcion
            else None
        ),
    }


def _ajustar_justificacion(registro):
    """
    Toda inasistencia nace injustificada hasta recibir el formulario en
    papel. Si la marca deja de computar inasistencia, el registro vuelve
    a "no aplica" y se descartan los datos del formulario.
    """
    Justificacion = RegistroAsistencia.EstadoJustificacion

    if not registro.marca.computa_inasistencia:
        registro.estado_justificacion = Justificacion.NO_APLICA
        registro.nro_formulario = ""
        registro.fecha_recepcion = None
        registro.recepcionado_por = None
    elif registro.estado_justificacion == Justificacion.NO_APLICA:
        registro.estado_justificacion = Justificacion.INJUSTIFICADA
