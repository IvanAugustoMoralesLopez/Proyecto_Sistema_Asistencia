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


@transaction.atomic
def copiar_calendario(*, usuario, anio_origen, anio_destino):
    _exigir_permiso(
        usuario,
        "asistencias.add_dianolaborable",
        "No tenés permiso para cargar días en el calendario.",
    )

    if not ANIO_MINIMO <= anio_destino <= ANIO_MAXIMO:
        raise ValidationError(
            f"El año destino debe estar entre {ANIO_MINIMO} y {ANIO_MAXIMO}."
        )

    dias_origen = DiaNoLaborable.objects.filter(fecha__year=anio_origen)

    creados = 0
    omitidos = 0

    for dia in dias_origen:
        try:
            nueva_fecha = dia.fecha.replace(year=anio_destino)
        except ValueError:
            omitidos += 1
            continue

        try:
            _validar_periodo_abierto(nueva_fecha)
        except ValidationError:
            omitidos += 1
            continue

        _, created = DiaNoLaborable.objects.get_or_create(
            fecha=nueva_fecha,
            defaults={"tipo": dia.tipo, "descripcion": dia.descripcion},
        )
        if created:
            creados += 1
        else:
            omitidos += 1

    return creados, omitidos


@transaction.atomic
def cargar_calendario_masivo(*, usuario, texto, tipo):
    from datetime import date

    _exigir_permiso(
        usuario,
        "asistencias.add_dianolaborable",
        "No tenés permiso para cargar días en el calendario.",
    )

    lineas = texto.strip().splitlines()
    creados = 0
    errores = []

    for i, linea in enumerate(lineas, 1):
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue

        partes = linea.split(None, 1)
        fecha_texto = partes[0]
        descripcion = partes[1].strip() if len(partes) > 1 else ""

        fecha = None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                fecha = date.fromisoformat(fecha_texto) if fmt == "%Y-%m-%d" else None
                if fecha is None:
                    from datetime import datetime
                    fecha = datetime.strptime(fecha_texto, fmt).date()
                break
            except ValueError:
                continue

        if fecha is None:
            errores.append(f"Línea {i}: '{fecha_texto}' no es una fecha.")
            continue

        if not ANIO_MINIMO <= fecha.year <= ANIO_MAXIMO:
            errores.append(
                f"Línea {i}: el año {fecha.year} está fuera del rango."
            )
            continue

        try:
            _validar_periodo_abierto(fecha)
        except ValidationError:
            errores.append(
                f"Línea {i}: el período de {fecha_texto} está cerrado."
            )
            continue

        _, created = DiaNoLaborable.objects.get_or_create(
            fecha=fecha,
            defaults={"tipo": tipo, "descripcion": descripcion},
        )
        if created:
            creados += 1

    return creados, errores
