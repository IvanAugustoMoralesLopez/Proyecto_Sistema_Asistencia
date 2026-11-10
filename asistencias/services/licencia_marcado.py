"""
Marcado automatico de asistencias por licencia (RN-07 / RF-14).

Al cargar una licencia (Desde/Hasta), `marcar_licencia` deja en
asistencias un registro por cada fecha habil del periodo, con la marca
LIC o LT. La llama el modulo de licencias; asistencias no depende de el.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from ..models import (
    CierreDiario,
    EventoAsistencia,
    MarcaAsistencia,
    RegistroAsistencia,
)
from .reglas import (
    DIA_HORARIO as _DIA_HORARIO,
    _ajustar_justificacion,
    _datos_registro,
    _validar_designacion_vigente,
    _validar_licencia,
    _validar_periodo_abierto,
    motivo_dia_no_laborable,
)

# Un articulo de licencia es de largo tratamiento (marca LT) si su tipo
# contiene este texto. Si el catalogo cambia la redaccion, se ajusta aca.
TEXTO_LARGO_TRATAMIENTO = "largo tratamiento"


def _codigo_de_marca(licencia):
    """LT para largo tratamiento; LIC para cualquier otra licencia."""
    tipo = licencia.articulo.tipo_licencia.lower()
    return "LT" if TEXTO_LARGO_TRATAMIENTO in tipo else "LIC"


def _motivo_de_omision(designacion, fecha):
    """
    Devuelve el motivo por el que no corresponde marcar la fecha, o None
    si corresponde. Usa las mismas reglas que la carga manual.
    """
    motivo = motivo_dia_no_laborable(fecha)
    if motivo:
        return motivo

    try:
        _validar_periodo_abierto(fecha)
        _validar_designacion_vigente(designacion, fecha)
    except ValidationError as exc:
        return " ".join(exc.messages)

    # Una jornada cerrada solo la modifica quien tiene autorizacion
    # (RN-06): el marcado automatico no la toca y lo informa.
    if CierreDiario.objects.filter(fecha=fecha).exists():
        return "La jornada esta cerrada"

    return None


def _marcar_dia(licencia, designacion, fecha, marca, horas, usuario):
    """Crea o actualiza el registro de la fecha. No duplica ni repite."""
    registro = (
        RegistroAsistencia.objects.select_for_update()
        .filter(designacion=designacion, fecha=fecha)
        .first()
    )
    motivo = f"Licencia {licencia.pk}"

    if registro is None:
        registro = RegistroAsistencia(
            designacion=designacion,
            fecha=fecha,
            marca=marca,
            horas_inasistidas=horas,
            licencia=licencia,
            creado_por=usuario,
            actualizado_por=usuario,
        )
        _ajustar_justificacion(registro)
        registro.save()
        EventoAsistencia.objects.create(
            asistencia=registro,
            usuario=usuario,
            accion=EventoAsistencia.Accion.CREAR,
            motivo=motivo,
            antes=None,
            despues=_datos_registro(registro),
        )
        return

    antes = _datos_registro(registro)

    registro.marca = marca
    registro.horas_inasistidas = horas
    registro.licencia = licencia
    # Un registro validado se corrige y vuelve a borrador, como en la
    # edicion manual, para que se valide de nuevo.
    registro.estado_registro = RegistroAsistencia.Estado.BORRADOR
    registro.actualizado_por = usuario
    _ajustar_justificacion(registro)

    despues = _datos_registro(registro)
    if antes == despues:
        return  # ya estaba marcado: no se repite el evento

    registro.save()
    EventoAsistencia.objects.create(
        asistencia=registro,
        usuario=usuario,
        accion=EventoAsistencia.Accion.EDITAR,
        motivo=motivo,
        antes=antes,
        despues=despues,
    )


@transaction.atomic
def marcar_licencia(licencia, usuario=None):
    """
    Marca en asistencias cada dia habil del periodo de la licencia, con
    las horas que la designacion tiene ese dia de la semana.

    Devuelve un resumen:
      - marcados: fechas en las que quedo un registro de licencia.
      - omitidos: (fecha, motivo) de los dias que no se marcaron.
      - sin_horario: fechas habiles en que la designacion no da clase.
      - advertencias: problemas de la licencia entera (sin fecha hasta,
        designacion sin horarios).
    """
    resumen = {
        "marcados": [],
        "omitidos": [],
        "sin_horario": [],
        "advertencias": [],
    }

    if licencia.hasta is None:
        resumen["advertencias"].append(
            "La licencia no tiene fecha 'hasta': no se marco ningun dia."
        )
        return resumen

    designacion = licencia.designacion
    horas_por_dia = {
        horario.dia: horario.horas_catedra
        for horario in designacion.horarios.all()
    }

    if not horas_por_dia:
        resumen["advertencias"].append(
            "La designacion no tiene horarios cargados: "
            "no se marco ningun dia."
        )
        return resumen

    codigo = _codigo_de_marca(licencia)
    marca = MarcaAsistencia.objects.filter(codigo=codigo).first()

    if marca is None:
        # El catálogo de marcas es cerrado (RF-08) y lo carga una migración:
        # si falta, es un problema de datos, no del operador.
        raise ValidationError(
            f"No existe la marca «{codigo}» en el catálogo de asistencias: "
            "no se pudo marcar la licencia."
        )

    fecha = licencia.desde

    while fecha <= licencia.hasta:
        motivo = _motivo_de_omision(designacion, fecha)
        horas = horas_por_dia.get(_DIA_HORARIO.get(fecha.weekday()))

        if motivo:
            resumen["omitidos"].append((fecha, motivo))
        elif not horas:
            # El docente no da clase ese dia: no es un problema.
            resumen["sin_horario"].append(fecha)
        else:
            # Dos decimales, como se guarda en la base: asi comparar con
            # un registro ya marcado no da una diferencia falsa.
            horas = Decimal(horas).quantize(Decimal("0.01"))
            _marcar_dia(licencia, designacion, fecha, marca, horas, usuario)
            resumen["marcados"].append(fecha)

        fecha += timedelta(days=1)

    return resumen 

def registros_huerfanos_de_licencia(licencia):
    """
    Registros de asistencia vinculados a la licencia que ya no la cumplen:
    su fecha quedo fuera del periodo o son de otra designacion (por ejemplo,
    despues de editar la licencia).

    No modifica nada: solo los detecta, para avisar al operador, que los
    corrige a mano desde la carga diaria. Usa la misma regla que la carga
    manual (_validar_licencia).
    """
    huerfanos = []
    registros = (
        licencia.asistencias_relacionadas
        .select_related("licencia", "designacion")
        .order_by("fecha")
    )

    for registro in registros:
        try:
            _validar_licencia(registro)
        except ValidationError:
            huerfanos.append(registro)

    return huerfanos