"""
Consultas y reglas de lectura de la app reportes.

Las vistas no arman querysets: piden acá los resultados ya filtrados.
Así las reglas (por ejemplo, la superposición de períodos) viven en un
solo lugar y se pueden probar o reutilizar sin pasar por HTTP.
"""

from datetime import datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone

from asistencias.models import EventoAsistencia
from licencias.models import LicenciaOtorgada
from licencias.services import dias_usados_en_anio


# ───────────── Bitácora (RF-20) ─────────────

def _inicio_del_dia(fecha):
    return timezone.make_aware(datetime.combine(fecha, time.min))


def buscar_eventos(filtros=None):
    """Eventos de la bitácora, del más reciente al más antiguo."""
    filtros = filtros or {}
    eventos = EventoAsistencia.objects.select_related(
        "usuario",
        "asistencia__designacion__persona",
        "cierre",
        "cierre_diario",
    ).order_by("-creado_en", "-pk")

    if filtros.get("usuario"):
        eventos = eventos.filter(usuario=filtros["usuario"])
    if filtros.get("accion"):
        eventos = eventos.filter(accion=filtros["accion"])
    if filtros.get("dni"):
        eventos = eventos.filter(
            asistencia__designacion__persona__dni=filtros["dni"].strip()
        )
    # Se comparan datetimes (y no __date) para no depender de las tablas
    # de zonas horarias de MySQL/MariaDB.
    if filtros.get("desde"):
        eventos = eventos.filter(creado_en__gte=_inicio_del_dia(filtros["desde"]))
    if filtros.get("hasta"):
        eventos = eventos.filter(
            creado_en__lt=_inicio_del_dia(filtros["hasta"] + timedelta(days=1))
        )
    return eventos


def describir_objetivo(evento):
    """Texto del registro al que se refiere el evento."""
    if evento.asistencia_id:
        registro = evento.asistencia
        persona = registro.designacion.persona
        return f"{persona.apellido_nombre} — {registro.fecha:%d/%m/%Y}"
    if evento.cierre_id:
        return f"Período {evento.cierre.anio}-{evento.cierre.mes:02d}"
    if evento.cierre_diario_id:
        return f"Jornada {evento.cierre_diario.fecha:%d/%m/%Y}"
    if evento.accion == EventoAsistencia.Accion.PARAMETROS:
        return "Parámetros del sistema"
    if evento.accion in (
        EventoAsistencia.Accion.USUARIO_ALTA,
        EventoAsistencia.Accion.USUARIO_EDITAR,
    ):
        datos = evento.despues if isinstance(evento.despues, dict) else {}
        return f"Usuario {datos.get('usuario', '—')}"
    return "—"


def resumir_cambios(evento):
    """Lista de (campo, antes, después) con lo que cambió en el evento."""
    antes = evento.antes if isinstance(evento.antes, dict) else {}
    despues = evento.despues if isinstance(evento.despues, dict) else {}
    return [
        (campo, antes.get(campo, "—"), despues.get(campo, "—"))
        for campo in despues
        if campo not in antes or antes[campo] != despues[campo]
    ]


# ───────────── Consultas de licencias (RF-17) ─────────────

def buscar_licencias(filtros=None):
    """Licencias otorgadas que cumplen todos los filtros indicados."""
    filtros = filtros or {}
    licencias = LicenciaOtorgada.objects.select_related(
        "designacion__persona",
        "designacion__cargo",
        "designacion__espacio_curricular__carrera",
        "articulo",
    ).order_by("-desde", "designacion__persona__apellido_nombre", "pk")

    if filtros.get("dni"):
        dni = filtros["dni"].replace(".", "").replace(" ", "")
        licencias = licencias.filter(designacion__persona__dni__startswith=dni)
    if filtros.get("apellido"):
        licencias = licencias.filter(
            designacion__persona__apellido_nombre__icontains=filtros["apellido"].strip()
        )
    if filtros.get("carrera"):
        licencias = licencias.filter(
            designacion__espacio_curricular__carrera=filtros["carrera"]
        )
    # La licencia entra si su período se superpone con el rango pedido.
    # Una licencia sin fecha "hasta" se considera abierta.
    if filtros.get("hasta"):
        licencias = licencias.filter(desde__lte=filtros["hasta"])
    if filtros.get("desde"):
        licencias = licencias.filter(
            Q(hasta__isnull=True) | Q(hasta__gte=filtros["desde"])
        )
    if filtros.get("tipo_licencia"):
        licencias = licencias.filter(articulo__tipo_licencia=filtros["tipo_licencia"])
    if filtros.get("disp_tipo"):
        licencias = licencias.filter(disp_tipo__icontains=filtros["disp_tipo"].strip())
    if filtros.get("disp_numero"):
        licencias = licencias.filter(disp_numero=filtros["disp_numero"].strip())
    if filtros.get("disp_anio"):
        licencias = licencias.filter(disp_anio=filtros["disp_anio"])

    estado = filtros.get("justifica")
    if estado == "si":
        licencias = licencias.filter(justifica=True)
    elif estado == "no":
        licencias = licencias.filter(justifica=False)
    elif estado == "pendiente":
        licencias = licencias.filter(justifica__isnull=True)
    return licencias


def texto_instrumento(licencia):
    """Texto legible del instrumento legal, ej. 'Disposición 12/2026'."""
    numero = licencia.disp_numero or ""
    if licencia.disp_anio:
        numero = f"{numero}/{licencia.disp_anio}" if numero else str(licencia.disp_anio)
    return " ".join(p for p in (licencia.disp_tipo, numero) if p) or "—"


# ───────────── Alertas de agotamiento (RF-18) ─────────────

UMBRAL_POR_DEFECTO = 80  # % del tope a partir del cual se avisa


def calcular_alertas(anio, umbral=UMBRAL_POR_DEFECTO):
    """
    Docentes que consumieron al menos `umbral` % del tope anual de días de
    un artículo de licencia. Solo se evalúan los artículos con tope numérico.

    Los días se calculan con licencias.services.dias_usados_en_anio, la misma
    regla de conteo del módulo de licencias. Un docente se evalúa por
    artículo, sumando todas las licencias de ese artículo en el año.
    """
    licencias = (
        LicenciaOtorgada.objects.filter(
            articulo__tope_dias_anual__isnull=False,
            articulo__tope_dias_anual__gt=0,
            desde__year__lte=anio,
        )
        .filter(Q(hasta__isnull=True) | Q(hasta__year__gte=anio))
        .select_related("designacion__persona", "articulo")
        .order_by("-desde", "-pk")
    )

    # Un renglón por (docente, artículo). Si el artículo tiene distinto tope
    # según la situación de revista, se usa el de la licencia más reciente.
    pares = {}
    for licencia in licencias:
        persona = licencia.designacion.persona
        pares.setdefault((persona.dni, licencia.articulo.articulo), licencia)

    alertas = []
    for (dni, codigo), licencia in pares.items():
        tope = licencia.articulo.tope_dias_anual
        usados = dias_usados_en_anio(dni, codigo, anio)
        porcentaje = round(usados * 100 / tope)
        if porcentaje >= umbral:
            alertas.append({
                "dni": dni,
                "docente": licencia.designacion.persona.apellido_nombre,
                "articulo": codigo,
                "tipo_licencia": licencia.articulo.tipo_licencia,
                "usados": usados,
                "tope": tope,
                "restantes": max(tope - usados, 0),
                "porcentaje": porcentaje,
                "agotado": usados >= tope,
            })

    alertas.sort(key=lambda a: (-a["porcentaje"], a["docente"]))
    return alertas
