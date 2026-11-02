"""
Alta y modificación de registros de asistencia (RF-07), individual o por
planilla completa del día.
"""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from ..models import EventoAsistencia, RegistroAsistencia
from .reglas import (
    MOTIVO_MINIMO,
    _ajustar_justificacion,
    _datos_registro,
    _exigir_permiso,
    _validar_designacion_vigente,
    _validar_jornada_abierta,
    _validar_licencia,
    _validar_marca_requisitos,
    _validar_motivo_maximo,
    _validar_periodo_abierto,
    validar_dia_laborable,
)
from .sesiones import _validar_sesion_edicion


@transaction.atomic
def guardar_asistencia(
    *,
    usuario,
    token,
    datos,
    registro_id=None,
    motivo="",
):
    """
    Crea o modifica una asistencia.
    Todas las modificaciones relevantes quedan registradas en eventos.
    """
    if registro_id is None:
        _exigir_permiso(
            usuario,
            "asistencias.add_registroasistencia",
            "No tenés permiso para registrar asistencia.",
        )
    else:
        _exigir_permiso(
            usuario,
            "asistencias.change_registroasistencia",
            "No tenés permiso para modificar asistencia.",
        )

    _validar_sesion_edicion(usuario, token)
    _validar_motivo_maximo(motivo)

    designacion = datos["designacion"]
    fecha = datos["fecha"]

    _validar_periodo_abierto(fecha)
    _validar_jornada_abierta(usuario, fecha, motivo)
    validar_dia_laborable(fecha)
    _validar_designacion_vigente(designacion, fecha)

    marca = datos["marca"]
    observaciones = datos.get("observaciones", "")

    if marca.requiere_observacion and not observaciones.strip():
        raise ValidationError(
            "La marca seleccionada requiere observaciones."
        )

    licencia = datos.get("licencia")
    horas_inasistidas = _validar_marca_requisitos(
        marca, datos.get("horas_inasistidas"), licencia
    )

    if registro_id is None:
        registro = RegistroAsistencia(
            designacion=designacion,
            fecha=fecha,
            marca=marca,
            horas_inasistidas=horas_inasistidas,
            licencia=licencia,
            observaciones=observaciones,
            creado_por=usuario,
            actualizado_por=usuario,
        )
        _ajustar_justificacion(registro)
        registro.full_clean()
        _validar_licencia(registro)

        try:
            registro.save()
        except IntegrityError as exc:
            raise ValidationError(
                "Ya existe un registro para esa designación y fecha."
            ) from exc

        accion = EventoAsistencia.Accion.CREAR
        antes = None

    else:
        try:
            registro = (
                RegistroAsistencia.objects.select_for_update()
                .select_related("marca", "licencia")
                .get(pk=registro_id)
            )
        except RegistroAsistencia.DoesNotExist as exc:
            raise ValidationError(
                "El registro que intentás modificar no existe."
            ) from exc

        _validar_periodo_abierto(registro.fecha)

        if registro.fecha != fecha:
            _validar_jornada_abierta(usuario, registro.fecha, motivo)

        antes = _datos_registro(registro)

        # Un registro validado solo se corrige con motivo y vuelve a
        # borrador para que se valide nuevamente.
        if registro.estado_registro == RegistroAsistencia.Estado.VALIDADO:
            if len(motivo.strip()) < MOTIVO_MINIMO:
                raise ValidationError(
                    "Para modificar un registro validado indicá el motivo "
                    f"del cambio (al menos {MOTIVO_MINIMO} caracteres)."
                )

            registro.estado_registro = RegistroAsistencia.Estado.BORRADOR

        registro.designacion = designacion
        registro.fecha = fecha
        registro.marca = marca
        registro.horas_inasistidas = horas_inasistidas
        registro.licencia = licencia
        registro.observaciones = observaciones
        registro.actualizado_por = usuario
        _ajustar_justificacion(registro)

        registro.full_clean()
        _validar_licencia(registro)
        registro.save()

        accion = EventoAsistencia.Accion.EDITAR

    EventoAsistencia.objects.create(
        asistencia=registro,
        usuario=usuario,
        accion=accion,
        motivo=motivo,
        antes=antes,
        despues=_datos_registro(registro),
    )

    return registro


class PlanillaConErrores(Exception):
    """Filas de la planilla rápida con errores: {designacion_id: mensaje}."""

    def __init__(self, errores):
        super().__init__("La planilla tiene filas con errores.")
        self.errores = errores


@transaction.atomic
def guardar_planilla(*, usuario, token, fecha, filas, motivo=""):
    """
    Registra de una vez las marcas de un día (RF-07). Cada fila es un dict
    con designacion, marca, horas_inasistidas, licencia y observaciones.
    Es todo o nada: si alguna fila falla no se guarda ninguna.
    """
    _exigir_permiso(
        usuario,
        "asistencias.add_registroasistencia",
        "No tenés permiso para registrar asistencia.",
    )
    _validar_sesion_edicion(usuario, token)
    _validar_motivo_maximo(motivo)

    if not filas:
        raise ValidationError("No marcaste ninguna asistencia.")

    # Errores que alcanzan a toda la planilla: se informan una sola vez.
    _validar_periodo_abierto(fecha)
    _validar_jornada_abierta(usuario, fecha, motivo)
    validar_dia_laborable(fecha)

    errores = {}
    registros = []

    for fila in filas:
        try:
            registros.append(
                guardar_asistencia(
                    usuario=usuario,
                    token=token,
                    datos={**fila, "fecha": fecha},
                    motivo=motivo,
                )
            )
        except ValidationError as exc:
            errores[fila["designacion"].pk] = " ".join(exc.messages)

    if errores:
        raise PlanillaConErrores(errores)

    return registros
