"""
Cálculo de días hábiles: ÚNICA fuente de verdad para RF-14, RN-07 y RN-08.

Este módulo NO importa modelos a nivel de módulo (solo dentro de
`obtener_feriados`), así que puede importarse desde models.py, services.py
y views.py sin generar importaciones circulares.
"""
from datetime import date, timedelta


def obtener_feriados(desde: date, hasta: date) -> set:
    """Fechas de DiaNoLaborable entre `desde` y `hasta` (inclusive), en un set."""
    if hasta < desde:
        return set()
    # Import local: asistencias es otra app y no queremos acoplar la carga de modelos.
    from asistencias.models import DiaNoLaborable

    return set(
        DiaNoLaborable.objects.filter(fecha__range=[desde, hasta])
        .values_list('fecha', flat=True)
    )


def es_dia_habil(fecha: date, feriados) -> bool:
    """Lunes a viernes y que no sea feriado/asueto."""
    return fecha.weekday() < 5 and fecha not in feriados


def listar_dias_habiles(desde: date, hasta: date, feriados=None) -> list:
    """
    Lista de fechas hábiles en [desde, hasta].

    Si `feriados` es None se consultan a la base (una sola query). Pasalos
    ya calculados cuando proceses muchos rangos seguidos.
    Sirve también para la propagación LIC/LT de RN-07.
    """
    if hasta < desde:
        return []
    if feriados is None:
        feriados = obtener_feriados(desde, hasta)
    cantidad = (hasta - desde).days + 1
    return [
        dia
        for dia in (desde + timedelta(days=i) for i in range(cantidad))
        if es_dia_habil(dia, feriados)
    ]


def contar_dias_habiles(desde: date, hasta: date, feriados=None) -> int:
    return len(listar_dias_habiles(desde, hasta, feriados))


def rango_en_anio(desde: date, hasta, anio: int, hoy: date = None):
    """
    Recorta el período de una licencia al año `anio`.

    - `hasta=None` (licencia abierta) se acota a `hoy`, sin pasar del 31/12,
      para no proyectar consumos futuros.
    - Devuelve (inicio, fin) o None si el período no toca ese año.
    """
    hoy = hoy or date.today()
    inicio = max(desde, date(anio, 1, 1))
    fin = min(hasta if hasta else hoy, date(anio, 12, 31))
    if fin < inicio:
        return None
    return inicio, fin
