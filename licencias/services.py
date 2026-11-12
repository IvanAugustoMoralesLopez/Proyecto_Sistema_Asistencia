import calendar
import unicodedata
from datetime import date

from django.db import transaction
from django.db.models import Q

from .clasificacion import (
    CategoriaSinPlanillaError,
    PLANILLA_IL01,
    PLANILLA_IL02,
    planilla_para_categoria,
)
from .dias import contar_dias_habiles, fecha_de_hoy, obtener_feriados, rango_en_anio
from .models import LicenciaArticulo, LicenciaOtorgada

def dias_usados_en_anio(dni: str, articulo: str, anio: int, excluir_id: int = None) -> int:
    """
    Días hábiles consumidos por el docente en `anio` para el artículo dado.

    `excluir_id`: id de una licencia que NO debe contarse. Se usa al editar,
    para que la licencia no se cuente contra sí misma. Por defecto no excluye
    nada, así que las llamadas existentes (reportes, etc.) siguen igual.
    """
    licencias = LicenciaOtorgada.objects.filter(
        designacion__persona__dni=dni,
        articulo__articulo=articulo,
        desde__year__lte=anio,
    ).filter(
        Q(hasta__isnull=True) | Q(hasta__year__gte=anio)
    )

    if excluir_id is not None:
        licencias = licencias.exclude(pk=excluir_id)

    # Una sola consulta de feriados para todo el año (antes era una por licencia).
    feriados = obtener_feriados(date(anio, 1, 1), date(anio, 12, 31))
    hoy = fecha_de_hoy()

    total_dias = 0
    for lic in licencias:
        rango = rango_en_anio(lic.desde, lic.hasta, anio, hoy)
        if rango is None:
            continue
        inicio, fin = rango
        total_dias += contar_dias_habiles(inicio, fin, feriados)

    return total_dias


def clasificar_planilla_licencia(licencia: LicenciaOtorgada) -> str:
    """
    Asigna la licencia a IL-01 (salud, RN-04) o IL-02 (administrativas, RN-05).
    Lanza CategoriaSinPlanillaError si la categoría del artículo no está
    contemplada en ninguna de las dos reglas.
    """
    return planilla_para_categoria(licencia.articulo.categoria_informe) 


DISPOSICION_TIPO = 'Disposición'


def _clave_alfabetica(licencia):
    """Clave de orden de RN-11: por apellido, sin distinguir tildes ni mayúsculas."""
    nombre = licencia.designacion.persona.apellido_nombre
    descompuesto = unicodedata.normalize('NFKD', nombre)
    sin_tildes = ''.join(c for c in descompuesto if not unicodedata.combining(c))
    return (sin_tildes.casefold(), licencia.desde, licencia.pk)


def _ultimo_numero_emitido(oficina, anio):
    """Mayor número de disposición ya usado en esa oficina y año (0 si no hay)."""
    mayor = 0
    numeros = LicenciaOtorgada.objects.filter(
        disp_oficina=oficina, disp_anio=anio,
    ).values_list('disp_numero', flat=True)
    for numero in numeros:
        if numero and numero.isdigit():
            mayor = max(mayor, int(numero))
    return mayor


def _clasificar_pendientes(anio: int, mes: int):
    """
    Licencias que empiezan en el mes y todavía no tienen disposición, separadas
    en (emitibles, omitidas), cada lista en orden alfabético (RN-11).
    - RN-10: solo son emitibles las que tienen N° de formulario en papel.
    - Lo ya emitido (con disp_numero) queda afuera.
    """
    if not 1 <= mes <= 12:
        raise ValueError("El mes debe estar entre 1 y 12.")

    primer_dia = date(anio, mes, 1)
    ultimo_dia = date(anio, mes, calendar.monthrange(anio, mes)[1])

    pendientes = LicenciaOtorgada.objects.filter(
        desde__gte=primer_dia,
        desde__lte=ultimo_dia,
    ).filter(
        Q(disp_numero__isnull=True) | Q(disp_numero='')
    ).select_related('designacion__persona', 'articulo')

    emitibles, omitidas = [], []
    for licencia in pendientes:
        if (licencia.nro_formulario or '').strip():
            emitibles.append(licencia)
        else:
            omitidas.append(licencia)

    emitibles.sort(key=_clave_alfabetica)
    omitidas.sort(key=_clave_alfabetica)
    return emitibles, omitidas


def _oficina_o_por_defecto(oficina):
    """`oficina` por defecto: la de ParametroSistema (RF-21)."""
    if oficina is None:
        # Import local: reportes importa licencias, no al revés.
        from reportes.models import ParametroSistema
        return ParametroSistema.obtener().codigo_oficina
    return oficina


def _numerar_por_docente(emitibles, ultimo_numero):
    """
    RN-11: todas las materias de un docente con el mismo período (mismo desde
    y hasta) comparten un único número de disposición. Devuelve la lista de
    (numero, licencia) en el mismo orden que `emitibles`, que ya viene
    ordenado alfabéticamente: el número crece solo al cambiar de docente o
    de período.
    """
    numeros = {}
    resultado = []
    numero = ultimo_numero
    for licencia in emitibles:
        clave = (licencia.designacion.persona_id, licencia.desde, licencia.hasta)
        if clave not in numeros:
            numero += 1
            numeros[clave] = numero
        resultado.append((numeros[clave], licencia))
    return resultado


def previsualizar_disposiciones_mes(anio: int, mes: int, oficina: str = None) -> dict:
    """
    Muestra qué haría emitir_disposiciones_mes sin guardar nada (RF-16).
    Devuelve {'a_emitir': [(numero, licencia)], 'omitidas': [licencia],
    'oficina': str}, con los números que se asignarían.
    """
    emitibles, omitidas = _clasificar_pendientes(anio, mes)
    oficina = _oficina_o_por_defecto(oficina)

    a_emitir = _numerar_por_docente(
        emitibles, _ultimo_numero_emitido(oficina, anio),
    )

    return {'a_emitir': a_emitir, 'omitidas': omitidas, 'oficina': oficina}


def emitir_disposiciones_mes(anio: int, mes: int, oficina: str = None) -> dict:
    """
    Emite las Disposiciones Internas de las licencias que empiezan en el mes
    (RF-16). Devuelve {'emitidas': [(numero, licencia)], 'omitidas': [licencia]}.

    - RN-10: solo se emiten las licencias con N° de formulario en papel; las
      demás quedan en 'omitidas' y no se tocan.
    - RN-11: se ordenan alfabéticamente por apellido y se numeran en forma
      correlativa, continuando desde el último número de la oficina y el año.
      Las materias del mismo docente y período comparten un único número.
    - Lo ya emitido (con disp_numero) no se vuelve a numerar.
    - `oficina` por defecto: la de ParametroSistema (RF-21).
    """
    emitibles, omitidas = _clasificar_pendientes(anio, mes)
    oficina = _oficina_o_por_defecto(oficina)

    emitidas = []
    with transaction.atomic():
        asignaciones = _numerar_por_docente(
            emitibles, _ultimo_numero_emitido(oficina, anio),
        )
        for numero, licencia in asignaciones:
            licencia.disp_tipo = DISPOSICION_TIPO
            licencia.disp_oficina = oficina
            licencia.disp_numero = str(numero)
            licencia.disp_anio = anio
            licencia.save(update_fields=[
                'disp_tipo', 'disp_oficina', 'disp_numero', 'disp_anio',
            ])
            emitidas.append((numero, licencia))

    return {'emitidas': emitidas, 'omitidas': omitidas}

TITULOS_PLANILLA = {
    PLANILLA_IL01: 'IL-01 Salud',
    PLANILLA_IL02: 'IL-02 Administrativas',
}
TITULO_SIN_PLANILLA = 'Sin planilla asignada'


def articulos_para_asistente(situacion: str = None) -> list:
    """
    RF-15: datos del catálogo para guiar la elección del artículo.

    Devuelve una lista de diccionarios (aptos para JSON) con la planilla de
    salida de cada artículo (IL-01 / IL-02), su tope, goce, plazo y autoridad.
    Si `situacion` viene (titular, interino, suplente), se filtra por ella sin
    distinguir mayúsculas. Un artículo con categoría sin planilla no rompe:
    queda con planilla None.
    """
    articulos = LicenciaArticulo.objects.all()
    if situacion:
        articulos = articulos.filter(sit_rev__iexact=situacion.strip())

    datos = []
    for articulo in articulos.order_by('articulo', 'sit_rev'):
        try:
            planilla = planilla_para_categoria(articulo.categoria_informe)
        except CategoriaSinPlanillaError:
            planilla = None
        datos.append({
            'id': articulo.pk,
            'articulo': articulo.articulo,
            'tipo_licencia': articulo.tipo_licencia,
            'situacion': (articulo.sit_rev or '').strip().lower(),
            'planilla': planilla,
            'planilla_titulo': TITULOS_PLANILLA.get(planilla, TITULO_SIN_PLANILLA),
            'tope_dias_anual': articulo.tope_dias_anual,
            'goce_haberes': articulo.goce_haberes,
            'plazo': articulo.plazo,
            'autoridad': articulo.autoridad,
        })
    return datos
