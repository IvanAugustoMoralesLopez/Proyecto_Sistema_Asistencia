from django import template

register = template.Library()

CAMPO_LEGIBLE = {
    "designacion_id": "Designación",
    "fecha": "Fecha",
    "marca_id": "Marca",
    "marca": "Marca",
    "horas_inasistidas": "Horas",
    "licencia_id": "Licencia",
    "observaciones": "Observaciones",
    "estado_registro": "Estado",
    "estado_justificacion": "Justificación",
    "nro_formulario": "N° formulario",
    "fecha_recepcion": "Fecha recepción",
    "estado": "Estado",
    "anio": "Año",
    "mes": "Mes",
    "version": "Versión",
    "registros": "Registros",
}


@register.filter
def json_legible(valor):
    if not valor or not isinstance(valor, dict):
        return "—"
    partes = []
    for clave, v in valor.items():
        nombre = CAMPO_LEGIBLE.get(clave, clave)
        partes.append(f"{nombre}: {v}")
    return " · ".join(partes) if partes else "—"


@register.filter
def diff_legible(antes, despues):
    if not antes or not despues or not isinstance(antes, dict) or not isinstance(despues, dict):
        return ""
    cambios = []
    for clave in sorted(set(antes) | set(despues)):
        va = antes.get(clave)
        vd = despues.get(clave)
        if va != vd:
            nombre = CAMPO_LEGIBLE.get(clave, clave)
            cambios.append(f"{nombre}: {va} → {vd}")
    return " · ".join(cambios) if cambios else "Sin cambios"


@register.filter
def rango_paginas(pagina):
    total = pagina.paginator.num_pages
    actual = pagina.number
    nums = {1, total}
    for i in range(max(1, actual - 2), min(total, actual + 2) + 1):
        nums.add(i)
    resultado = []
    anterior = 0
    for p in sorted(nums):
        if p - anterior > 1:
            resultado.append(0)
        resultado.append(p)
        anterior = p
    return resultado
