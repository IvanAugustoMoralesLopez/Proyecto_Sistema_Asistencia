from datetime import date

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
            'cod_licencia': articulo.cod_licencia,
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
