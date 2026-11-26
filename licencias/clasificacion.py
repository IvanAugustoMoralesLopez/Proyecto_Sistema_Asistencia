"""
Clasificación estricta de licencias en planillas IL-01 / IL-02 (RF-15, RN-04, RN-05).

Es la ÚNICA fuente de verdad: los `choices` del modelo y la función de
clasificación salen del mismo diccionario, así que no pueden desincronizarse.
No importa modelos, por lo que se puede usar desde cualquier módulo.
"""

PLANILLA_IL01 = 'IL-01'
PLANILLA_IL02 = 'IL-02'

CATEGORIAS_POR_PLANILLA = {
    # RN-04: licencias médicas y afecciones de salud. Con el nomenclador
    # oficial: todo lo de la Agrupación 1 («Licencias por razones de salud»).
    PLANILLA_IL01: (
        'Enfermedad común',
        'Corto tratamiento',
        'Largo tratamiento',
        'Enfermedad familiar',
        # Nomenclador, Agrupación 1
        'Accidente de trabajo',
        'Maternidad',
        'Tareas pasivas',
        'Traslado por salud',
    ),
    # RN-05: el resto de las licencias y los permisos. Con el nomenclador
    # oficial: Agrupación 2 («Otras licencias») y Agrupación 3 («Permisos»).
    PLANILLA_IL02: (
        'Razones particulares',
        'Examen',
        'Duelo',
        'Matrimonio',
        'Compensatorio',
        'Comisión de servicio',
        # Nomenclador, Agrupación 2
        'Licencia anual',
        'Adopción',
        'Estudio',
        'Representación gremial',
        'Cargo político',
        'Incompatibilidad',
        'Ascenso',
        'Inasistencia justificada',
        'Cambio de funciones',
        'Donación',
        'Estudios médicos',
        'Licencia especial',
        'Deportiva',
        'Violencia de género',
        'Jubilación',
        # Nomenclador, Agrupación 3
        'Nacimiento',
        'Credo',
        'Lactancia',
        'Natalicio',
        'Citación judicial',
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
