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
    _validar_horas_maximas,
    _validar_jornada_abierta,
    _validar_licencia,
    _validar_marca_requisitos,
    _validar_motivo_maximo,
    _validar_periodo_abierto,
    validar_dia_laborable,
)
from .pendientes import iniciar_seguimiento
from .sesiones import _validar_sesion_edicion


def _aplicar_formulario(registro, recibido, nro_formulario, usuario):
    """La inasistencia con el papel ya recibido queda justificada."""
    from django.utils import timezone

    if not recibido or registro.marca.codigo != "I":
        return

    registro.estado_justificacion = (
        RegistroAsistencia.EstadoJustificacion.JUSTIFICADA
    )
    registro.nro_formulario = nro_formulario
    registro.fecha_recepcion = registro.fecha_recepcion or timezone.localdate()
    registro.recepcionado_por = usuario


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

    if registro_id is None:
        _validar_designacion_vigente(designacion, fecha)

    marca = datos["marca"]
    observaciones = datos.get("observaciones", "")

    if marca.requiere_observacion and not observaciones.strip():
        raise ValidationError(
            "La marca seleccionada requiere observaciones."
        )

    licencia = datos.get("licencia")
    # Apartado de inasistencia de la carga diaria: si ya se recibió el
    # formulario en papel, la falta nace justificada (el número es opcional).
    formulario_recibido = datos.get("formulario_recibido", False)
    nro_formulario = (datos.get("nro_formulario") or "").strip()[:30]
    horas_inasistidas = _validar_marca_requisitos(
        marca, datos.get("horas_inasistidas"), licencia
    )
    _validar_horas_maximas(designacion, fecha, horas_inasistidas)

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
        _aplicar_formulario(registro, formulario_recibido, nro_formulario, usuario)
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

        # RF-11: un registro ya cargado se corrige aunque después se haya dado
        # de baja la designación o el legajo, si la fecha está dentro de su
        # vigencia. Pasarlo a otra designación sí exige que esa esté activa.
        _validar_designacion_vigente(
            designacion,
            fecha,
            corrigiendo=designacion.pk == registro.designacion_id,
        )

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
        _aplicar_formulario(registro, formulario_recibido, nro_formulario, usuario)

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

    # Una falta sin formulario o una LIC sin licencia quedan en seguimiento.
    iniciar_seguimiento(registro)

    return registro


@transaction.atomic
def aplicar_al_agente(*, usuario, token, registro, motivo=""):
    """
    RF-07 / RF-11: la novedad diaria es una sola por agente y jornada. Al
    corregir la marca de una materia, la misma marca se lleva a las demás
    materias que el docente ya tiene cargadas ese día, cada una con las
    horas de su horario. Devuelve los registros que cambiaron.
    """
    from .agenda import horas_del_dia

    otros = (
        RegistroAsistencia.objects.select_related(
            "designacion__persona", "marca"
        )
        .prefetch_related("designacion__horarios")
        .filter(
            fecha=registro.fecha,
            designacion__persona_id=registro.designacion.persona_id,
        )
        .exclude(pk=registro.pk)
    )
    marca = registro.marca
    cambiados = []

    for otro in otros:
        if otro.marca_id == marca.pk:
            continue

        horas = horas_del_dia(otro.designacion, registro.fecha)

        if marca.requiere_horas and horas <= 0:
            horas = otro.horas_inasistidas or registro.horas_inasistidas

        cambiados.append(
            guardar_asistencia(
                usuario=usuario,
                token=token,
                datos={
                    "designacion": otro.designacion,
                    "fecha": registro.fecha,
                    "marca": marca,
                    "horas_inasistidas": horas,
                    "licencia": None,
                    "observaciones": registro.observaciones,
                },
                registro_id=otro.pk,
                motivo=motivo,
            )
        )

    return cambiados


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
