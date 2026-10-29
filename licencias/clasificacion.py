"""
Planillas IL-01 / IL-02 (RF-15, RN-04, RN-05).

En la base (planilla_personal.sql v4) `licencia_articulo.categoria_informe` es un
ENUM('IL-01','IL-02') NOT NULL: la planilla de cada artículo se decide al cargar
el catálogo, y RN-04 / RN-05 se cumplen cargando bien cada artículo.
IL-01 = salud (médicas, corto/largo tratamiento, enfermedad familiar).
IL-02 = administrativas (razones particulares, exámenes, duelo, matrimonio,
        compensatorios, comisiones de servicio).

Este módulo no importa modelos, así que se puede usar desde cualquier lado.
"""

PLANILLA_IL01 = 'IL-01'
PLANILLA_IL02 = 'IL-02'

PLANILLA_CHOICES = [
    (PLANILLA_IL01, 'IL-01 (Salud)'),
    (PLANILLA_IL02, 'IL-02 (Administrativas)'),
]

PLANILLAS_VALIDAS = frozenset(valor for valor, _ in PLANILLA_CHOICES)


class CategoriaSinPlanillaError(ValueError):
    """El artículo no tiene una planilla válida (IL-01 / IL-02)."""


def planilla_para_categoria(categoria) -> str:
    """
    Devuelve 'IL-01' o 'IL-02' a partir de `categoria_informe`.
    Si el valor no es una planilla válida (dato viejo, vacío, etc.) lanza
    CategoriaSinPlanillaError en lugar de asignar IL-02 por defecto.
    """
    if categoria in PLANILLAS_VALIDAS:
        return categoria
    raise CategoriaSinPlanillaError(
        f"El artículo tiene categoria_informe={categoria!r}; debe ser "
        f"'IL-01' o 'IL-02' (RN-04/RN-05). Corregilo en el catálogo."
    )
