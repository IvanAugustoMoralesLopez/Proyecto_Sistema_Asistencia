"""
Calendario escolar (RF-10): feriados, asuetos y días inhábiles.

Junto con los fines de semana, `DiaNoLaborable` define los días sin
obligación de marcado (ver `reglas.motivo_dia_no_laborable`). Cambiar el
calendario de un período ya cerrado alteraría después de cerrado qué
asistencias eran válidas, por eso no se permite.
"""

from django.core.exceptions import ValidationError
from django.db import transaction

from ..models import DiaNoLaborable, RegistroAsistencia
from .reglas import _exigir_permiso, _validar_periodo_abierto

# Mismo rango de años que el cierre mensual (CierreMensualForm).
ANIO_MINIMO = 2000
ANIO_MAXIMO = 2100


def _obtener_bloqueado(dia_id):
    try:
        return DiaNoLaborable.objects.select_for_update().get(pk=dia_id)
    except DiaNoLaborable.DoesNotExist as exc:
        raise ValidationError("El día del calendario no existe.") from exc


@transaction.atomic
def guardar_dia_no_laborable(*, usuario, datos, dia_id=None):
    """
    Carga un día en el calendario, o modifica el `dia_id` indicado.

    El día se vuelve a leer de la base: el formulario ya cambió su
    instancia al validar y no sirve para saber en qué período estaba.
    """
    if dia_id is None:
        _exigir_permiso(
            usuario,
            "asistencias.add_dianolaborable",
            "No tenés permiso para cargar días en el calendario.",
        )
        dia = DiaNoLaborable()
    else:
        _exigir_permiso(
            usuario,
            "asistencias.change_dianolaborable",
            "No tenés permiso para modificar el calendario.",
        )
        dia = _obtener_bloqueado(dia_id)
        _validar_periodo_abierto(dia.fecha)

    _validar_periodo_abierto(datos["fecha"])

    dia.fecha = datos["fecha"]
    dia.tipo = datos["tipo"]
    dia.descripcion = datos.get("descripcion", "")
    dia.save()

    return dia


@transaction.atomic
def eliminar_dia_no_laborable(*, usuario, dia_id):
    _exigir_permiso(
        usuario,
        "asistencias.delete_dianolaborable",
        "No tenés permiso para eliminar días del calendario.",
    )

    dia = _obtener_bloqueado(dia_id)
    _validar_periodo_abierto(dia.fecha)
    dia.delete()

    return dia


def registros_cargados(fecha):
    """Asistencias ya cargadas en la fecha, que el calendario no modifica."""
    return RegistroAsistencia.objects.filter(fecha=fecha).count()
