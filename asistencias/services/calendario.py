"""
Calendario escolar (RF-10): feriados, asuetos y días inhábiles.

El calendario es visual y organizativo: la pantalla diaria muestra el día
con fondo e indicador (ver `reglas.aviso_del_calendario`), pero no bloquea
la carga ni cambia el cómputo de días u horas. El calendario de un período
ya cerrado no se modifica, para que lo que se vio al cerrar no cambie.

RF-20: cada alta, modificación y baja queda en la bitácora con el usuario,
la fecha y lo que había antes y después.
"""

from django.core.exceptions import ValidationError
from django.db import transaction

from ..models import DiaNoLaborable, EventoAsistencia, RegistroAsistencia
from .reglas import (
    ANIO_MAXIMO,
    ANIO_MINIMO,
    _exigir_permiso,
    _validar_periodo_abierto,
)

# ANIO_MINIMO y ANIO_MAXIMO viven en `reglas` (son el rango de fechas de todo
# el módulo) y se reexportan acá para no cambiar las importaciones existentes.
__all__ = [
    "ANIO_MAXIMO",
    "ANIO_MINIMO",
    "cargar_calendario_masivo",
    "copiar_calendario",
    "eliminar_dia_no_laborable",
    "guardar_dia_no_laborable",
    "registros_cargados",
]


def _obtener_bloqueado(dia_id):
    try:
        return DiaNoLaborable.objects.select_for_update().get(pk=dia_id)
    except DiaNoLaborable.DoesNotExist as exc:
        raise ValidationError("El día del calendario no existe.") from exc


def _foto(dia):
    """Datos del día que se guardan en la bitácora."""
    return {
        "fecha": dia.fecha.isoformat(),
        "tipo": dia.tipo,
        "descripcion": dia.descripcion,
    }


def _descripcion(dia):
    """«Feriado 09/07/2026 (Día de la Independencia)», para leer la bitácora."""
    texto = f"{dia.get_tipo_display()} {dia.fecha:%d/%m/%Y}"
    if dia.descripcion:
        texto += f" ({dia.descripcion})"
    return texto


def _registrar(usuario, accion, dia, *, antes=None, despues=None, origen=""):
    """RF-20: deja el cambio del calendario en la bitácora."""
    motivo = f"{origen}{_descripcion(dia)}"
    EventoAsistencia.objects.create(
        usuario=usuario,
        accion=accion,
        motivo=motivo[: EventoAsistencia._meta.get_field("motivo").max_length],
        antes=antes,
        despues=despues,
    )


@transaction.atomic
def guardar_dia_no_laborable(*, usuario, datos, dia_id=None):
    """
    Carga un día en el calendario, o modifica el `dia_id` indicado.

    El día se vuelve a leer de la base: el formulario ya cambió su
    instancia al validar y no sirve para saber en qué período estaba.
    """
    antes = None

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
        antes = _foto(dia)

    _validar_periodo_abierto(datos["fecha"])

    dia.fecha = datos["fecha"]
    dia.tipo = datos["tipo"]
    dia.descripcion = datos.get("descripcion", "")
    dia.save()

    despues = _foto(dia)

    if antes is None:
        _registrar(usuario, EventoAsistencia.Accion.CALENDARIO_ALTA, dia, despues=despues)
    elif antes != despues:
        _registrar(
            usuario, EventoAsistencia.Accion.CALENDARIO_EDITAR, dia,
            antes=antes, despues=despues,
        )

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
    antes = _foto(dia)
    dia.delete()
    _registrar(usuario, EventoAsistencia.Accion.CALENDARIO_BAJA, dia, antes=antes)

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

        nuevo, created = DiaNoLaborable.objects.get_or_create(
            fecha=nueva_fecha,
            defaults={"tipo": dia.tipo, "descripcion": dia.descripcion},
        )
        if created:
            creados += 1
            _registrar(
                usuario, EventoAsistencia.Accion.CALENDARIO_ALTA, nuevo,
                despues=_foto(nuevo), origen=f"Copia del calendario {anio_origen}: ",
            )
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

        nuevo, created = DiaNoLaborable.objects.get_or_create(
            fecha=fecha,
            defaults={"tipo": tipo, "descripcion": descripcion},
        )
        if created:
            creados += 1
            _registrar(
                usuario, EventoAsistencia.Accion.CALENDARIO_ALTA, nuevo,
                despues=_foto(nuevo), origen="Carga masiva: ",
            )

    return creados, errores
