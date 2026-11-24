"""
Pestaña «Mes» de la pantalla Asistencia del día: la planilla mensual de
consulta, con filtro por carrera, exportación a CSV e impresión.
"""

import csv

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.text import slugify

from personal.models import Carrera

from ..services import (
    COLUMNAS_TOTALES,
    SIN_CARRERA,
    carreras_del_mes,
    id_admitido,
    mes_pedido,
    mes_vecino,
    nombre_mes,
    planilla_del_mes,
)
from ._comun import vista_protegida


class ParametroInvalido(ValueError):
    """El mes o la carrera de la URL no sirven."""


def _parametros(request):
    """
    (primer día del mes, filtro de carrera, carrera elegida, valor del
    filtro) a partir de `?mes=AAAA-MM&carrera=<id|sin>`.
    """
    hoy = timezone.localdate()
    primero = mes_pedido(request.GET.get("mes"), hoy.replace(day=1))
    if primero is None:
        raise ParametroInvalido("El mes elegido no es válido.")

    valor = (request.GET.get("carrera") or "").strip()
    if not valor:
        return primero, None, None, ""
    if valor == SIN_CARRERA:
        return primero, SIN_CARRERA, None, SIN_CARRERA

    carrera = Carrera.objects.filter(pk=id_admitido(valor)).first()
    if carrera is None:
        raise ParametroInvalido("La carrera elegida no existe.")
    return primero, carrera, carrera, str(carrera.pk)


def _volver_al_mes(request):
    """Ante un parámetro inválido, se vuelve al mes pedido sin la carrera."""
    hoy = timezone.localdate()
    primero = mes_pedido(request.GET.get("mes"), hoy.replace(day=1)) or hoy.replace(day=1)
    return redirect(f"{request.path}?mes={primero:%Y-%m}")


@vista_protegida("asistencias.view_registroasistencia")
def planilla_mes(request):
    try:
        primero, filtro, carrera, carrera_valor = _parametros(request)
    except ParametroInvalido as exc:
        messages.error(request, str(exc))
        return _volver_al_mes(request)

    hoy = timezone.localdate()
    planilla = planilla_del_mes(primero.year, primero.month, filtro, hoy=hoy)
    carreras, hay_sin_carrera = carreras_del_mes(primero.year, primero.month)
    anterior = mes_vecino(primero, -1)
    siguiente = mes_vecino(primero, 1)

    return render(
        request,
        "asistencias/planilla_mes.html",
        {
            "planilla": planilla,
            "columnas_totales": COLUMNAS_TOTALES,
            "titulo_mes": nombre_mes(primero),
            "mes_valor": f"{primero:%Y-%m}",
            "mes_anterior": f"{anterior:%Y-%m}" if anterior else "",
            "mes_siguiente": f"{siguiente:%Y-%m}" if siguiente else "",
            "carreras": carreras,
            "hay_sin_carrera": hay_sin_carrera or filtro == SIN_CARRERA,
            "carrera": carrera,
            "carrera_valor": carrera_valor,
            "sin_carrera": SIN_CARRERA,
            "filtro_sin_carrera": filtro == SIN_CARRERA,
            # Pestaña «Día»: hoy si se mira el mes en curso, si no el día 1.
            "pestana_fecha": (
                hoy if (hoy.year, hoy.month) == (primero.year, primero.month) else primero
            ).isoformat(),
            "pestana_mes": f"{primero:%Y-%m}",
        },
    )


@vista_protegida("asistencias.view_registroasistencia")
def planilla_mes_csv(request):
    try:
        primero, filtro, carrera, _ = _parametros(request)
    except ParametroInvalido as exc:
        messages.error(request, str(exc))
        return _volver_al_mes(request)

    planilla = planilla_del_mes(primero.year, primero.month, filtro)

    nombre = f"asistencia_{primero:%Y-%m}"
    if carrera is not None:
        nombre += f"_{slugify(carrera.nombre)}"
    elif filtro == SIN_CARRERA:
        nombre += "_sin-carrera"

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{nombre}.csv"'
    # BOM y «;»: Excel en español abre el archivo con acentos y en columnas.
    response.write("﻿")
    writer = csv.writer(response, delimiter=";")

    writer.writerow([f"Asistencia de {nombre_mes(primero)}"] + (
        [f"Carrera: {carrera.nombre}"] if carrera is not None
        else ["Sin carrera"] if filtro == SIN_CARRERA
        else ["Todas las carreras"]
    ))
    writer.writerow(
        ["N°", "Apellido y nombre", "DNI"]
        + [str(dia["numero"]) for dia in planilla["dias"]]
        + [titulo for _, titulo in COLUMNAS_TOTALES]
    )
    for fila in planilla["filas"]:
        writer.writerow(
            [fila["numero"], fila["persona"].apellido_nombre, fila["persona"].dni]
            + [celda["texto"] for celda in fila["celdas"]]
            + [fila["totales"][clave] or "" for clave, _ in COLUMNAS_TOTALES]
        )

    return response
