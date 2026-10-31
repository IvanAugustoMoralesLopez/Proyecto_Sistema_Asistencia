"""
Clasificación estricta de licencias en planillas IL-01 / IL-02 (RF-15, RN-04, RN-05).

Es la ÚNICA fuente de verdad: los `choices` del modelo y la función de
clasificación salen del mismo diccionario, así que no pueden desincronizarse.
No importa modelos, por lo que se puede usar desde cualquier módulo.
"""

PLANILLA_IL01 = 'IL-01'
PLANILLA_IL02 = 'IL-02'

CATEGORIAS_POR_PLANILLA = {
    # RN-04: licencias médicas, afecciones de salud, corto y largo tratamiento
    # y enfermedad familiar.
    PLANILLA_IL01: (
        'Enfermedad común',
        'Corto tratamiento',
        'Largo tratamiento',
        'Enfermedad familiar',
    ),
    # RN-05: razones particulares, exámenes, duelo, matrimonio,
    # compensatorios y comisiones de servicio.
    PLANILLA_IL02: (
        'Razones particulares',
        'Examen',
        'Duelo',
        'Matrimonio',
        'Compensatorio',
        'Comisión de servicio',
    ),
}

PLANILLA_POR_CATEGORIA = {
    categoria: planilla
    for planilla, categorias in CATEGORIAS_POR_PLANILLA.items()
    for categoria in categorias
}

CATEGORIA_CHOICES = [
    (categoria, categoria)
    for categorias in CATEGORIAS_POR_PLANILLA.values()
    for categoria in categorias
]


class CategoriaSinPlanillaError(ValueError):
    """La categoría del artículo no corresponde a IL-01 ni a IL-02."""


def planilla_para_categoria(categoria: str) -> str:
    """
    Devuelve 'IL-01' o 'IL-02'. Si la categoría no está en RN-04/RN-05
    lanza CategoriaSinPlanillaError en lugar de asignar IL-02 por defecto.
    """
    try:
        return PLANILLA_POR_CATEGORIA[categoria]
    except KeyError:
        raise CategoriaSinPlanillaError(
            f"La categoría {categoria!r} no tiene planilla asignada "
            f"(RN-04/RN-05). Corregila en el catálogo de artículos."
        ) from None
