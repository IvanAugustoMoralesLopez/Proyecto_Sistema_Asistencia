"""
Planilla mensual de asistencia: una fila por docente y una columna por cada
día del mes, como la hoja «ASISTENCIA» del Excel de la bedel.

Se arma con lo cargado en la diaria (`RegistroAsistencia`), el horario de
cada designación, el calendario escolar y, para las columnas de licencia por
categoría, el artículo de la licencia otorgada o el imputado en la planilla
IL-01 / IL-02.

Solo lee; no guarda nada.
"""

import calendar
import unicodedata
from collections import defaultdict
from datetime import date

from django.db.models import Q
from django.utils import timezone

from ..models import DiaNoLaborable, RegistroAsistencia
from .agenda import horas_del_dia
from .reglas import DIAS_HABILES, MESES, anio_admitido

# Si el docente tuvo marcas distintas en sus materias el mismo día, la celda
# muestra la de mayor peso; el detalle por materia queda en el globo de ayuda.
PRIORIDAD_MARCA = ("LT", "LIC", "P", "I", "PR")

MARCA_PRESENTE = "PR"
MARCA_INASISTENCIA = "I"
MARCA_PERMISO = "P"
MARCAS_LICENCIA = ("LIC", "LT")

# Día con clase que todavía no se cargó.
PENDIENTE = "·"

# Valor del filtro de carrera para las designaciones que no tienen carrera
# (por ejemplo, un cargo que no dicta una materia).
SIN_CARRERA = "sin"

# Columnas de licencia por categoría del artículo. Todo lo que no es
# Enfermedad común ni Largo tratamiento va a OTROS.
CATEGORIA_ENF_COMUN = "Enfermedad común"
CATEGORIA_LARGO_TRAT = "Largo tratamiento"
COLUMNAS_TOTALES = (
    ("presentes", "Presentes"),
    ("faltas", "Faltas"),
    ("permisos", "Permisos"),
    ("licencia", "Licencia"),
    ("enf_comun", "ENF COMUN"),
    ("largo_trat", "LARGO TRAT"),
    ("otros", "OTROS"),
)


def mes_pedido(texto, por_defecto):
    """
    Primer día del mes pedido como «AAAA-MM» (el valor de un
    `<input type="month">`). Sin texto devuelve `por_defecto`; si el texto
    no sirve o el año está fuera del rango admitido, None.
    """
    if not texto:
        return por_defecto

    partes = texto.split("-")
    if len(partes) != 2 or not all(p.isdecimal() for p in partes):
        return None

    anio, mes = int(partes[0]), int(partes[1])
    if not anio_admitido(anio) or not 1 <= mes <= 12:
        return None

    return date(anio, mes, 1)


def mes_vecino(primer_dia, meses):
    """Primer día del mes corrido `meses` (±1), o None si se sale del rango."""
    indice = primer_dia.year * 12 + primer_dia.month - 1 + meses
    anio, mes = divmod(indice, 12)
    return date(anio, mes + 1, 1) if anio_admitido(anio) else None


def nombre_mes(primer_dia):
    """«Noviembre 2026»."""
    return f"{MESES[primer_dia.month - 1].capitalize()} {primer_dia.year}"


def _rango(anio, mes):
    return date(anio, mes, 1), date(anio, mes, calendar.monthrange(anio, mes)[1])


def _clave_alfabetica(texto):
    descompuesto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in descompuesto if not unicodedata.combining(c)).casefold()


def _vigente(designacion, fecha):
    return designacion.desde <= fecha and (
        designacion.hasta is None or fecha <= designacion.hasta
    )


def _filtrar_por_carrera(designaciones, carrera):
    if carrera is None:
        return designaciones
    if carrera == SIN_CARRERA:
        return designaciones.filter(carrera__isnull=True)
    return designaciones.filter(carrera=carrera)


def _designaciones_del_mes(primero, ultimo):
    """
    Designaciones vigentes en algún día del mes, más las que tienen algo
    cargado en el mes aunque ya no estén vigentes: así no queda ningún
    registro fuera de la planilla.
    """
    from personal.models import Designacion

    vigentes = Q(activo=True, persona__activa=True, desde__lte=ultimo) & (
        Q(hasta__isnull=True) | Q(hasta__gte=primero)
    )
    con_registros = Q(
        pk__in=RegistroAsistencia.objects.filter(
            fecha__range=(primero, ultimo)
        ).values("designacion_id")
    )
    return Designacion.objects.filter(vigentes | con_registros)


def carreras_del_mes(anio, mes):
    """
    Opciones del filtro de carrera: las carreras activas y las que tienen
    docentes en el mes. Devuelve (carreras, hay_sin_carrera).
    """
    from personal.models import Carrera

    primero, ultimo = _rango(anio, mes)
    del_mes = _designaciones_del_mes(primero, ultimo)
    carreras = Carrera.objects.filter(
        Q(activa=True) | Q(pk__in=del_mes.values("carrera_id"))
    ).order_by("nombre")
    return list(carreras), del_mes.filter(carrera__isnull=True).exists()


def _dias_del_mes(primero, ultimo):
    calendario = {
        dia.fecha: dia
        for dia in DiaNoLaborable.objects.filter(fecha__range=(primero, ultimo))
    }
    dias = []
    for numero in range(1, ultimo.day + 1):
        fecha = primero.replace(day=numero)
        no_laborable = calendario.get(fecha)

        if no_laborable is not None:
            motivo = no_laborable.get_tipo_display()
            if no_laborable.descripcion:
                motivo += f": {no_laborable.descripcion}"
        elif fecha.weekday() not in DIAS_HABILES:
            motivo = "Fin de semana"
        else:
            motivo = ""

        dias.append({
            "numero": numero,
            "fecha": fecha,
            "gris": bool(motivo),
            "motivo": motivo,
        })
    return dias


def _categorias_de_planilla_il(anio, mes, ids):
    """
    Categoría del artículo imputado en la planilla IL a las licencias del
    mes que no tienen licencia otorgada vinculada:
    {designacion_id: [(desde, hasta, categoria)]}.
    """
    from licencias.models import RenglonMensual

    imputadas = defaultdict(list)
    for renglon in RenglonMensual.objects.filter(
        anio=anio,
        mes=mes,
        designacion_id__in=ids,
        marca__in=MARCAS_LICENCIA,
        articulo__isnull=False,
    ).values("designacion_id", "desde", "hasta", "articulo__categoria_informe"):
        imputadas[renglon["designacion_id"]].append(
            (renglon["desde"], renglon["hasta"], renglon["articulo__categoria_informe"])
        )
    return imputadas


def _columna_de_licencia(registro, fecha, imputadas):
    """
    Columna (enf_comun, largo_trat u otros) en la que cuenta un día de
    licencia, o None si todavía no se sabe la categoría: una LIC sin
    licencia otorgada ni artículo imputado cuenta solo en «Licencia».
    """
    categoria = registro["licencia__articulo__categoria_informe"]

    if not categoria:
        for desde, hasta, de_la_planilla in imputadas.get(registro["designacion_id"], ()):
            if desde <= fecha <= hasta:
                categoria = de_la_planilla
                break

    if not categoria and registro["marca__codigo"] == "LT":
        categoria = CATEGORIA_LARGO_TRAT

    if not categoria:
        return None
    if categoria == CATEGORIA_ENF_COMUN:
        return "enf_comun"
    if categoria == CATEGORIA_LARGO_TRAT:
        return "largo_trat"
    return "otros"


def _nombre_de_materia(designacion, con_carrera):
    nombre = (
        designacion.espacio_curricular.nombre
        if designacion.espacio_curricular_id
        else designacion.cargo.descripcion
    )
    if con_carrera and designacion.carrera_id:
        nombre += f" ({designacion.carrera.nombre})"
    return nombre


def _prioridad(codigo):
    return (
        PRIORIDAD_MARCA.index(codigo)
        if codigo in PRIORIDAD_MARCA
        else len(PRIORIDAD_MARCA)
    )


def planilla_del_mes(anio, mes, carrera=None, hoy=None):
    """
    Planilla del mes: una fila por docente con una celda por día y los
    totales de la derecha.

    `carrera` es None (todas), `SIN_CARRERA` o una `Carrera`: con una carrera
    elegida solo cuentan las materias del docente en esa carrera.

    Cada celda tiene:
    - `texto`: la marca (PR, I, P, LIC, LT), «·» si ese día tenía clase y
      todavía no se cargó nada (solo hasta hoy y en días que no están en
      gris), o vacío si no tenía clase.
    - `clase`: para el color (pr, i, p, lic, lt, pend).
    - `mixta`: el docente tuvo marcas distintas en sus materias ese día.
    - `detalle`: qué pasó en cada materia, para el globo de ayuda.

    Los totales cuentan días, no materias: un día con dos materias en falta
    es una falta. Un día puede contar en dos columnas si en una materia faltó
    y en otra tuvo permiso.
    """
    primero, ultimo = _rango(anio, mes)
    hoy = hoy or timezone.localdate()
    dias = _dias_del_mes(primero, ultimo)

    designaciones = list(
        _filtrar_por_carrera(_designaciones_del_mes(primero, ultimo), carrera)
        .select_related("persona", "cargo", "espacio_curricular", "carrera")
        .prefetch_related("horarios")
        .order_by("persona_id", "pk")
    )
    ids = [d.pk for d in designaciones]

    registro_de = {
        (r["designacion_id"], r["fecha"]): r
        for r in RegistroAsistencia.objects.filter(
            designacion_id__in=ids, fecha__range=(primero, ultimo)
        ).values(
            "designacion_id",
            "fecha",
            "marca__codigo",
            "marca__descripcion",
            "marca__descripcion_simple",
            "licencia__articulo__categoria_informe",
        )
    }
    imputadas = _categorias_de_planilla_il(anio, mes, ids) if ids else {}

    por_persona = defaultdict(list)
    for designacion in designaciones:
        por_persona[designacion.persona_id].append(designacion)

    filas = []
    for propias in por_persona.values():
        filas.append(_fila_del_docente(propias, dias, registro_de, imputadas, hoy, carrera))

    filas.sort(key=lambda f: (_clave_alfabetica(f["persona"].apellido_nombre), f["persona"].dni))
    for numero, fila in enumerate(filas, 1):
        fila["numero"] = numero

    totales = {clave: sum(f["totales"][clave] for f in filas) for clave, _ in COLUMNAS_TOTALES}
    totales["sin_cargar"] = sum(f["sin_cargar"] for f in filas)
    totales["docentes"] = len(filas)

    return {
        "anio": anio,
        "mes": mes,
        "dias": dias,
        "filas": filas,
        "totales": totales,
    }


def _fila_del_docente(propias, dias, registro_de, imputadas, hoy, carrera):
    persona = propias[0].persona
    # Sin filtro de carrera, la carrera ayuda a distinguir la misma materia
    # dictada en dos carreras.
    con_carrera = carrera is None and len({d.carrera_id for d in propias}) > 1
    totales = {clave: 0 for clave, _ in COLUMNAS_TOTALES}
    sin_cargar = 0
    celdas = []

    for dia in dias:
        fecha = dia["fecha"]
        codigos = set()
        columnas_licencia = set()
        detalle = []
        pendiente = False

        for designacion in propias:
            materia = _nombre_de_materia(designacion, con_carrera)
            registro = registro_de.get((designacion.pk, fecha))

            if registro is not None:
                codigo = registro["marca__codigo"]
                codigos.add(codigo)
                etiqueta = registro["marca__descripcion_simple"] or registro["marca__descripcion"]
                detalle.append(f"{materia}: {etiqueta} ({codigo})")
                if codigo in MARCAS_LICENCIA:
                    columna = _columna_de_licencia(registro, fecha, imputadas)
                    if columna:
                        columnas_licencia.add(columna)
            elif (
                not dia["gris"]
                and fecha <= hoy
                and designacion.activo
                and _vigente(designacion, fecha)
                and horas_del_dia(designacion, fecha) > 0
            ):
                pendiente = True
                detalle.append(f"{materia}: sin cargar")

        # La marca de más peso: una novedad (LT, LIC, P, I) le gana a PR.
        codigo = min(codigos, key=_prioridad) if codigos else ""

        if MARCA_PRESENTE in codigos:
            totales["presentes"] += 1
        if MARCA_INASISTENCIA in codigos:
            totales["faltas"] += 1
        if MARCA_PERMISO in codigos:
            totales["permisos"] += 1
        if codigos & set(MARCAS_LICENCIA):
            totales["licencia"] += 1
        for columna in columnas_licencia:
            totales[columna] += 1
        if pendiente:
            sin_cargar += 1

        if codigo:
            texto, clase = codigo, codigo.lower()
        elif pendiente:
            texto, clase = PENDIENTE, "pend"
        else:
            texto, clase = "", ""

        estados = len(codigos) + (1 if pendiente else 0)
        celdas.append({
            "texto": texto,
            "clase": clase,
            "gris": dia["gris"],
            "mixta": estados > 1,
            "detalle": (
                f"{fecha:%d/%m} · " + " · ".join(detalle) if detalle else dia["motivo"]
            ),
        })

    return {
        "persona": persona,
        "celdas": celdas,
        "totales": totales,
        # En el orden de COLUMNAS_TOTALES, para recorrerlos en la plantilla.
        "totales_en_orden": [totales[clave] for clave, _ in COLUMNAS_TOTALES],
        "sin_cargar": sin_cargar,
    }
