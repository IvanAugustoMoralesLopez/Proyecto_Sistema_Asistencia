"""
Consultas y reglas de lectura de la app reportes.

Las vistas no arman querysets: piden acá los resultados ya filtrados.
Así las reglas (por ejemplo, la superposición de períodos) viven en un
solo lugar y se pueden probar o reutilizar sin pasar por HTTP.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone

from asistencias.models import EventoAsistencia, RegistroAsistencia
from licencias.models import LicenciaOtorgada
from licencias.services import dias_usados_en_anio

from .auditoria import AccionesReportes


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
        dni = filtros["dni"].strip()
        # Los eventos de asistencia se ligan por el registro; los de licencias
        # guardan el DNI dentro de antes/después.
        eventos = eventos.filter(
            Q(asistencia__designacion__persona__dni=dni)
            | Q(despues__dni=dni)
            | Q(antes__dni=dni)
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


_A = AccionesReportes
_OBJETIVO_FIJO = {
    _A.LICENCIA_ALTA: "Licencia otorgada",
    _A.LICENCIA_EDITAR: "Licencia otorgada",
    _A.LICENCIA_BAJA: "Licencia otorgada",
    _A.CATALOGO_ALTA: "Catálogo",
    _A.CATALOGO_EDITAR: "Catálogo",
    _A.CATALOGO_BAJA: "Catálogo",
    _A.IMPORTACION: "Importación de personal",
}


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
    if evento.accion in _OBJETIVO_FIJO:
        return _OBJETIVO_FIJO[evento.accion]
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
    if not despues and antes:  # baja: se muestra lo que había
        return [(campo, valor, "—") for campo, valor in antes.items()]
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
    if filtros.get("espacio_curricular"):
        licencias = licencias.filter(
            designacion__espacio_curricular=filtros["espacio_curricular"]
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


# ───────────── Consulta unificada: licencias + ausencias/permisos (RF-17) ─────────────

ORIGEN_TODOS = "todos"
ORIGEN_LICENCIAS = "licencias"
ORIGEN_AUSENCIAS = "ausencias"

# Filtros que solo existen para licencias otorgadas (artículo e instrumento
# legal). Si se usa alguno, las ausencias simples no pueden cumplirlo.
FILTROS_SOLO_LICENCIAS = ("tipo_licencia", "disp_tipo", "disp_numero", "disp_anio")

_JUSTIFICA_A_ESTADO = {
    "si": RegistroAsistencia.EstadoJustificacion.JUSTIFICADA,
    "no": RegistroAsistencia.EstadoJustificacion.INJUSTIFICADA,
    "pendiente": RegistroAsistencia.EstadoJustificacion.EN_TRAMITE,
}
_JUSTIFICA_TEXTO = {True: "Sí", False: "No", None: "Sin definir"}


@dataclass(frozen=True)
class FilaConsulta:
    """Una fila de la consulta, venga de una licencia o de una ausencia."""

    origen: str          # "Licencia" o "Ausencia"
    pk: int
    dni: str
    docente: str
    cargo: str
    carrera: str
    materia: str
    codigo: str          # código de licencia (vacío en ausencias)
    articulo: str        # artículo de licencia (vacío en ausencias)
    tipo: str            # tipo de licencia o descripción de la marca
    sit_rev: str
    desde: date
    hasta: date | None
    instrumento: str     # instrumento legal o Nº de formulario
    justifica: str

    @property
    def es_licencia(self):
        return self.origen == "Licencia"


def _fila_de_licencia(lic):
    designacion = lic.designacion
    espacio = designacion.espacio_curricular
    return FilaConsulta(
        origen="Licencia",
        pk=lic.pk,
        dni=designacion.persona.dni,
        docente=designacion.persona.apellido_nombre,
        cargo=str(designacion.cargo),
        carrera=str(espacio.carrera) if espacio else "",
        materia=espacio.nombre if espacio else "",
        codigo=lic.articulo.cod_licencia,
        articulo=lic.articulo.articulo,
        tipo=lic.articulo.tipo_licencia,
        sit_rev=lic.sit_rev,
        desde=lic.desde,
        hasta=lic.hasta,
        instrumento=texto_instrumento(lic),
        justifica=_JUSTIFICA_TEXTO[lic.justifica],
    )


def _fila_de_ausencia(registro):
    designacion = registro.designacion
    espacio = designacion.espacio_curricular
    formulario = f"Formulario {registro.nro_formulario}" if registro.nro_formulario else "—"
    return FilaConsulta(
        origen="Ausencia",
        pk=registro.pk,
        dni=designacion.persona.dni,
        docente=designacion.persona.apellido_nombre,
        cargo=str(designacion.cargo),
        carrera=str(espacio.carrera) if espacio else "",
        materia=espacio.nombre if espacio else "",
        codigo="",
        articulo="",
        tipo=registro.marca.descripcion,
        sit_rev="",
        desde=registro.fecha,
        hasta=registro.fecha,
        instrumento=formulario,
        justifica=registro.get_estado_justificacion_display(),
    )


def buscar_ausencias(filtros=None):
    """
    Ausencias y permisos simples: registros diarios que computan inasistencia
    (Inasistencia, Presente retirado) y que no están amparados por una
    licencia otorgada. Las licencias ya se consultan como licencias.
    """
    filtros = filtros or {}
    registros = RegistroAsistencia.objects.filter(
        marca__computa_inasistencia=True,
        licencia__isnull=True,
    ).select_related(
        "designacion__persona",
        "designacion__cargo",
        "designacion__espacio_curricular__carrera",
        "marca",
    ).order_by("-fecha", "designacion__persona__apellido_nombre", "pk")

    if filtros.get("dni"):
        dni = filtros["dni"].replace(".", "").replace(" ", "")
        registros = registros.filter(designacion__persona__dni__startswith=dni)
    if filtros.get("apellido"):
        registros = registros.filter(
            designacion__persona__apellido_nombre__icontains=filtros["apellido"].strip()
        )
    if filtros.get("carrera"):
        registros = registros.filter(
            designacion__espacio_curricular__carrera=filtros["carrera"]
        )
    if filtros.get("espacio_curricular"):
        registros = registros.filter(
            designacion__espacio_curricular=filtros["espacio_curricular"]
        )
    if filtros.get("desde"):
        registros = registros.filter(fecha__gte=filtros["desde"])
    if filtros.get("hasta"):
        registros = registros.filter(fecha__lte=filtros["hasta"])
    if filtros.get("justifica") in _JUSTIFICA_A_ESTADO:
        registros = registros.filter(
            estado_justificacion=_JUSTIFICA_A_ESTADO[filtros["justifica"]]
        )
    return registros


class ConsultaCombinada:
    """
    Secuencia perezosa de FilaConsulta que une licencias y ausencias.

    Sirve para el Paginator (len + slicing) sin cargar todo en memoria:
    para una página se piden a cada fuente solo las primeras `stop` filas,
    se mezclan por fecha descendente y se corta la página.

    Orden: cada fuente ya viene ordenada por la base (fecha descendente,
    apellido, id). La mezcla solo compara la fecha entre fuentes y respeta
    el orden de la base dentro de cada una; si hay empate de fecha entre
    una licencia y una ausencia, va primero la licencia. Como Python no
    vuelve a ordenar por apellido, el criterio es el mismo (el de la base)
    en todas las páginas y no se repiten ni se omiten filas entre ellas.
    """

    def __init__(self, licencias=None, ausencias=None):
        self.licencias = licencias
        self.ausencias = ausencias

    @staticmethod
    def _mezclar(licencias, ausencias):
        """Une dos listas ya ordenadas por fecha descendente, de forma estable."""
        filas = [(-f.desde.toordinal(), 0, i, f) for i, f in enumerate(licencias)]
        filas += [(-f.desde.toordinal(), 1, i, f) for i, f in enumerate(ausencias)]
        filas.sort(key=lambda t: t[:3])
        return [t[3] for t in filas]

    def count(self):
        total = 0
        if self.licencias is not None:
            total += self.licencias.count()
        if self.ausencias is not None:
            total += self.ausencias.count()
        return total

    def __len__(self):
        return self.count()

    def _primeras(self, cantidad):
        licencias = []
        ausencias = []
        if self.licencias is not None:
            licencias = [_fila_de_licencia(x) for x in self.licencias[:cantidad]]
        if self.ausencias is not None:
            ausencias = [_fila_de_ausencia(x) for x in self.ausencias[:cantidad]]
        return self._mezclar(licencias, ausencias)

    def __getitem__(self, indice):
        if isinstance(indice, slice):
            inicio, fin, paso = indice.indices(self.count())
            return self._primeras(fin)[inicio:fin:paso]
        if indice < 0:
            indice += self.count()
        return self._primeras(indice + 1)[indice]

    def __iter__(self):
        """Recorre todo (para exportar): une ambas fuentes sin repetir consultas."""
        licencias = []
        ausencias = []
        if self.licencias is not None:
            licencias = [_fila_de_licencia(x) for x in self.licencias.iterator()]
        if self.ausencias is not None:
            ausencias = [_fila_de_ausencia(x) for x in self.ausencias.iterator()]
        return iter(self._mezclar(licencias, ausencias))


def buscar_consulta(filtros=None):
    """
    Consulta única de RF-17: licencias otorgadas y ausencias/permisos simples
    con los mismos filtros (docente, carrera, materia, fechas, justificación).

    El filtro «origen» elige qué mostrar. Los filtros propios de las
    licencias (tipo, instrumento legal) dejan afuera las ausencias.
    """
    filtros = filtros or {}
    origen = filtros.get("origen") or ORIGEN_TODOS
    solo_licencias = any(filtros.get(c) for c in FILTROS_SOLO_LICENCIAS)

    licencias = None
    ausencias = None
    if origen in (ORIGEN_TODOS, ORIGEN_LICENCIAS):
        licencias = buscar_licencias(filtros)
    if origen in (ORIGEN_TODOS, ORIGEN_AUSENCIAS) and not solo_licencias:
        ausencias = buscar_ausencias(filtros)
    return ConsultaCombinada(licencias, ausencias)


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
