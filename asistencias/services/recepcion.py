"""
Recepción del formulario en papel (RF-09) y validación de registros.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from ..models import EventoAsistencia, MarcaAsistencia, RegistroAsistencia
from .reglas import (
    MOTIVO_MINIMO,
    _datos_registro,
    _exigir_permiso,
    _validar_licencia,
    _validar_motivo_maximo,
    _validar_periodo_abierto,
)
from .sesiones import _validar_sesion_edicion


# RF-09: marcas que se pueden asignar al recibir el formulario en papel.
MARCAS_AL_RECEPCIONAR = ("LIC", "LT", "P")

TRANSICIONES_JUSTIFICACION = {
    RegistroAsistencia.EstadoJustificacion.INJUSTIFICADA: {
        RegistroAsistencia.EstadoJustificacion.EN_TRAMITE,
        RegistroAsistencia.EstadoJustificacion.JUSTIFICADA,
    },
    RegistroAsistencia.EstadoJustificacion.EN_TRAMITE: {
        RegistroAsistencia.EstadoJustificacion.JUSTIFICADA,
        RegistroAsistencia.EstadoJustificacion.INJUSTIFICADA,
    },
}


@transaction.atomic
def recepcionar_formulario(
    *,
    usuario,
    token,
    registro_id,
    nuevo_estado,
    nro_formulario="",
    fecha_recepcion=None,
    motivo="",
    nueva_marca="",
):
    """
    Cambia el estado de justificación de una inasistencia al recibir (o
    rechazar) el formulario en papel. Injustificada pasa a en trámite o
    justificada; en trámite pasa a justificada o vuelve a injustificada.

    RF-09: con `nueva_marca` ("LIC", "LT" o "P") el registro deja de ser una
    inasistencia (I) y pasa a la marca que corresponde al formulario. RF-07:
    como la novedad es una por agente y jornada, el cambio alcanza también a
    las otras materias del docente que ese día tenían la misma inasistencia.
    """
    _exigir_permiso(
        usuario,
        "asistencias.recepcionar_formulario",
        "No tenés permiso para recepcionar formularios.",
    )
    _validar_sesion_edicion(usuario, token)

    Justificacion = RegistroAsistencia.EstadoJustificacion

    try:
        registro = (
            RegistroAsistencia.objects.select_for_update()
            .select_related("marca")
            .get(pk=registro_id)
        )
    except RegistroAsistencia.DoesNotExist as exc:
        raise ValidationError(
            "El registro que intentás modificar no existe."
        ) from exc

    _validar_periodo_abierto(registro.fecha)

    if not registro.marca.computa_inasistencia:
        raise ValidationError(
            "El registro no es una inasistencia: no admite formulario."
        )

    if nuevo_estado not in Justificacion.values:
        raise ValidationError("El estado de justificación no es válido.")

    if nuevo_estado not in TRANSICIONES_JUSTIFICACION.get(
        registro.estado_justificacion, set()
    ):
        raise ValidationError(
            "No se puede pasar de "
            f"{registro.get_estado_justificacion_display().lower()} a "
            f"{Justificacion(nuevo_estado).label.lower()}."
        )

    nro_formulario = nro_formulario.strip()
    motivo = motivo.strip()
    _validar_motivo_maximo(motivo)

    maximo_formulario = RegistroAsistencia._meta.get_field(
        "nro_formulario"
    ).max_length

    if len(nro_formulario) > maximo_formulario:
        raise ValidationError(
            "El número de formulario no puede superar los "
            f"{maximo_formulario} caracteres."
        )

    nueva_marca = (nueva_marca or "").strip().upper()
    marca_nueva = None

    if nueva_marca:
        if nueva_marca not in MARCAS_AL_RECEPCIONAR:
            raise ValidationError(
                "Al recibir el formulario la marca solo puede pasar a "
                "Licencia (LIC), Largo tratamiento (LT) o Permiso (P)."
            )

        if nuevo_estado == Justificacion.INJUSTIFICADA:
            raise ValidationError(
                "Si rechazás el formulario la marca sigue siendo Inasistencia."
            )

        marca_nueva = MarcaAsistencia.objects.get(codigo=nueva_marca)

    if nuevo_estado == Justificacion.INJUSTIFICADA:
        if len(motivo) < MOTIVO_MINIMO:
            raise ValidationError(
                "Para rechazar el formulario indicá el motivo "
                f"(al menos {MOTIVO_MINIMO} caracteres)."
            )

        nro_formulario = ""
        fecha_recepcion = None
    else:
        if not nro_formulario:
            raise ValidationError(
                "Indicá el número del formulario recepcionado."
            )

        fecha_recepcion = fecha_recepcion or timezone.localdate()

        if fecha_recepcion > timezone.localdate():
            raise ValidationError(
                "La fecha de recepción no puede ser futura."
            )

    afectados = [registro]

    if marca_nueva is not None:
        # RF-07: las otras materias del docente con la misma inasistencia
        # ese día reciben el mismo formulario.
        afectados += list(
            RegistroAsistencia.objects.select_for_update()
            .select_related("marca")
            .filter(
                fecha=registro.fecha,
                designacion__persona_id=registro.designacion.persona_id,
                marca=registro.marca,
                estado_justificacion=registro.estado_justificacion,
            )
            .exclude(pk=registro.pk)
        )

    for afectado in afectados:
        antes = _datos_registro(afectado)

        afectado.estado_justificacion = nuevo_estado
        afectado.nro_formulario = nro_formulario
        afectado.fecha_recepcion = fecha_recepcion
        afectado.recepcionado_por = (
            usuario if nuevo_estado != Justificacion.INJUSTIFICADA else None
        )

        if marca_nueva is not None:
            afectado.marca = marca_nueva
            if marca_nueva.requiere_observacion and not afectado.observaciones.strip():
                afectado.observaciones = (
                    f"{marca_nueva.descripcion} - formulario N° {nro_formulario}"
                )

        afectado.actualizado_por = usuario
        afectado.save()

        EventoAsistencia.objects.create(
            asistencia=afectado,
            usuario=usuario,
            accion=EventoAsistencia.Accion.RECEPCIONAR,
            motivo=motivo,
            antes=antes,
            despues=_datos_registro(afectado),
        )

    return registro


@transaction.atomic
def validar_asistencia(*, usuario, token, registro_id):
    _exigir_permiso(
        usuario,
        "asistencias.validar_registro",
        "No tenés permiso para validar registros.",
    )
    _validar_sesion_edicion(usuario, token)

    try:
        registro = (
            RegistroAsistencia.objects.select_for_update()
            .select_related("designacion", "marca")
            .get(pk=registro_id)
        )
    except RegistroAsistencia.DoesNotExist as exc:
        raise ValidationError(
            "El registro que intentás validar no existe."
        ) from exc

    # Validar de nuevo no cambia nada y dejaría un evento VALIDAR de más.
    if registro.estado_registro == RegistroAsistencia.Estado.VALIDADO:
        raise ValidationError("El registro ya está validado.")

    _validar_periodo_abierto(registro.fecha)

    registro.full_clean()
    _validar_licencia(registro)

    antes = _datos_registro(registro)
    registro.estado_registro = RegistroAsistencia.Estado.VALIDADO
    registro.actualizado_por = usuario
    registro.save()

    EventoAsistencia.objects.create(
        asistencia=registro,
        usuario=usuario,
        accion=EventoAsistencia.Accion.VALIDAR,
        antes=antes,
        despues=_datos_registro(registro),
    )

    return registro


@transaction.atomic
def validar_multiples(*, usuario, token, registro_ids):
    _exigir_permiso(
        usuario,
        "asistencias.validar_registro",
        "No tenés permiso para validar registros.",
    )
    _validar_sesion_edicion(usuario, token)

    registros = (
        RegistroAsistencia.objects.select_for_update()
        .select_related("designacion", "marca")
        .filter(
            pk__in=registro_ids,
            estado_registro=RegistroAsistencia.Estado.BORRADOR,
        )
    )

    validados = 0

    for registro in registros:
        _validar_periodo_abierto(registro.fecha)
        registro.full_clean()
        _validar_licencia(registro)

        antes = _datos_registro(registro)
        registro.estado_registro = RegistroAsistencia.Estado.VALIDADO
        registro.actualizado_por = usuario
        registro.save()

        EventoAsistencia.objects.create(
            asistencia=registro,
            usuario=usuario,
            accion=EventoAsistencia.Accion.VALIDAR,
            antes=antes,
            despues=_datos_registro(registro),
        )
        validados += 1

    return validados
