"""
Agenda del día: qué docentes dan clase en una fecha y con cuántas horas.

Es la base del autocompletado de la carga diaria. El horario de cada
designación ya está cargado en Personal (`personal.Horario`: un día de la
semana y las horas cátedra de ese día), así que la planilla no necesita que
el operador vuelva a escribirlo todos los días: lo deduce de acá.

Este módulo solo lee; no guarda nada.
"""

from collections import defaultdict
from decimal import Decimal

from .reglas import clave_dia


def horas_del_dia(designacion, fecha):
    """
    Horas cátedra que la designación tiene en esa fecha, como Decimal.

    Devuelve Decimal("0") si ese día no da clase. Usa los horarios ya
    traídos con `prefetch_related("horarios")` cuando están disponibles,
    para no hacer una consulta por cada fila de la planilla.
    """
    dia = clave_dia(fecha)

    if dia is None:
        return Decimal("0")

    total = sum(
        horario.horas_catedra
        for horario in designacion.horarios.all()
        if horario.dia == dia
    )
    # Dos decimales, como se guarda en la base: así comparar con un registro
    # ya cargado no da una diferencia falsa.
    return Decimal(total).quantize(Decimal("0.01"))


def horario_del_dia(designacion, fecha):
    """Primer `Horario` de la designación en esa fecha, o None."""
    dia = clave_dia(fecha)

    if dia is None:
        return None

    for horario in designacion.horarios.all():
        if horario.dia == dia:
            return horario

    return None


def dias_con_clase(designacion):
    """Claves de día ('LUN'…'VIE') en las que la designación da clase."""
    return sorted({horario.dia for horario in designacion.horarios.all()})


def licencias_por_designacion(licencias):
    """Agrupa licencias por designación: {designacion_id: [licencia, …]}."""
    agrupadas = defaultdict(list)

    for licencia in licencias:
        agrupadas[licencia.designacion_id].append(licencia)

    return agrupadas


def ciclo_lectivo_actual():
    """
    Ciclo lectivo configurado en los parámetros del sistema (RF-21).

    Import local: `reportes` importa `asistencias`, no al revés.
    """
    from reportes.models import ParametroSistema

    return ParametroSistema.obtener().ciclo_lectivo
