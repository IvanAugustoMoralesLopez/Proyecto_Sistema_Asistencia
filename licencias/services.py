from datetime import date

from django.db.models import Q

from .clasificacion import (
    CategoriaSinPlanillaError,
    PLANILLA_IL01,
    PLANILLA_IL02,
    planilla_para_categoria,
)
from .dias import (
    contar_dias_habiles,
    fecha_de_hoy,
    limites_del_ciclo,
    listar_dias_habiles,
    obtener_feriados,
    rango_en_anio,
    rango_en_ciclo,
)
from .models import LicenciaArticulo, LicenciaOtorgada

def dias_usados_en_ciclo(
    dni: str,
    articulo,
    ciclo: int,
    excluir_id: int = None,
    excluir_grupo=None,
) -> int:
    """
    Días hábiles consumidos por el docente en el ciclo lectivo `ciclo` para
    el artículo dado (RN-08). El ciclo va del día 1 del mes que fija
    ParametroSistema.mes_inicio_ciclo hasta el día anterior un año después.

    `articulo`: un LicenciaArticulo (cuenta ese código del nomenclador) o el
    número de artículo como texto (cuenta todos los códigos con ese número).

    `excluir_id`: id de una licencia que NO debe contarse. Se usa al editar,
    para que la licencia no se cuente contra sí misma. `excluir_grupo`: el
    pedido que se está cargando o editando, que tampoco se cuenta.

    Se cuentan DÍAS DEL DOCENTE, no licencias: una licencia por docente se
    guarda como una LicenciaOtorgada por materia, y el mismo día en dos
    materias es un solo día consumido.
    """
    primero, ultimo = limites_del_ciclo(ciclo)
    licencias = LicenciaOtorgada.objects.filter(
        designacion__persona__dni=dni,
        desde__lte=ultimo,
    ).filter(
        Q(hasta__isnull=True) | Q(hasta__gte=primero)
    )
    if isinstance(articulo, LicenciaArticulo):
        licencias = licencias.filter(articulo=articulo)
    else:
        licencias = licencias.filter(articulo__articulo=articulo)

    if excluir_id is not None:
        licencias = licencias.exclude(pk=excluir_id)
    if excluir_grupo is not None:
        licencias = licencias.exclude(grupo=excluir_grupo)

    # Una sola consulta de feriados para todo el ciclo.
    feriados = obtener_feriados(primero, ultimo)
    hoy = fecha_de_hoy()

    dias = set()
    for lic in licencias:
        rango = rango_en_ciclo(lic.desde, lic.hasta, ciclo, hoy)
        if rango is None:
            continue
        inicio, fin = rango
        dias.update(listar_dias_habiles(inicio, fin, feriados))

    return len(dias)


# Nombre anterior: el «año» del tope ahora es el ciclo lectivo.
dias_usados_en_anio = dias_usados_en_ciclo


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
