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


def designaciones_del_dia(fecha, texto="", solo_con_clase=False):
    """
    Designaciones vigentes en la fecha, ordenadas por docente.

    `solo_con_clase` deja solo a quienes tienen horario cargado ese día de la
    semana. Import local de personal: evita acoplar la carga de modelos.
    """
    from django.db.models import Q

    from personal.models import Designacion

    designaciones = (
        Designacion.objects.filter(
            activo=True,
            persona__activa=True,
            desde__lte=fecha,
        )
        .filter(Q(hasta__isnull=True) | Q(hasta__gte=fecha))
        .select_related("persona", "cargo", "espacio_curricular")
        .prefetch_related("horarios")
        .order_by("persona__apellido_nombre", "persona_id", "id")
    )

    if texto:
        designaciones = designaciones.filter(
            Q(persona__apellido_nombre__icontains=texto)
            | Q(persona__dni__icontains=texto)
        )

    dia = clave_dia(fecha)

    if solo_con_clase and dia:
        # distinct(): una designación con varios horarios ese día se repetiría.
        designaciones = designaciones.filter(horarios__dia=dia).distinct()

    return designaciones


def conteo_del_dia(fecha):
    """
    Cuántos docentes corresponden a la fecha y cuántos ya están cargados.

    Es lo que la pantalla diaria necesita para poder decir «faltan cargar 12»
    en vez de limitarse a mostrar una tabla vacía. Usa el mismo criterio que
    la pantalla de carga: los que dan clase ese día y, si nadie tiene horario
    cargado todavía, todos los vigentes.
    """
    from ..models import RegistroAsistencia

    ids = list(
        designaciones_del_dia(fecha, solo_con_clase=True)
        .values_list("pk", flat=True)
    )

    if not ids:
        ids = list(
            designaciones_del_dia(fecha).values_list("pk", flat=True)
        )

    cargados = (
        RegistroAsistencia.objects
        .filter(fecha=fecha, designacion_id__in=ids)
        .count()
    )

    return {
        "total": len(ids),
        "cargados": cargados,
        "pendientes": max(len(ids) - cargados, 0),
    }
