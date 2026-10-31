from datetime import date

from django.db.models import Q

from .clasificacion import planilla_para_categoria
from .dias import contar_dias_habiles, obtener_feriados, rango_en_anio
from .models import LicenciaOtorgada


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
    hoy = date.today()

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
