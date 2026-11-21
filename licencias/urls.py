from django.urls import path

from .views import (
    nueva_licencia,
    detalle_licencia,
    pendientes_licencias,
    nueva_licencia_otorgada,
    listado_licencias_otorgadas,
    editar_licencia_otorgada,
    reporte_mensual_licencias,
    generador_disposiciones,
    planilla_mensual,
    planilla_mensual_csv,
    resoluciones_licencia,
    descargar_resolucion,
)

app_name = "licencias"

urlpatterns = [
    # Licencia por docente: la que usan el menú, la diaria y los pendientes.
    path(
        "nueva-por-docente/",
        nueva_licencia,
        name="nueva_licencia",
    ),
    path(
        "pendientes/",
        pendientes_licencias,
        name="pendientes",
    ),
    path(
        "<int:licencia_id>/",
        detalle_licencia,
        name="detalle_licencia",
    ),
    # Alta por materia (una sola designación): se conserva para casos puntuales.
    path(
        "nueva/",
        nueva_licencia_otorgada,
        name="nueva_licencia_otorgada",
    ),
    path(
        "listado/",
        listado_licencias_otorgadas,
        name="listado_licencias_otorgadas",
    ),
    path(
        "editar/<int:licencia_id>/",
        editar_licencia_otorgada,
        name="editar_licencia_otorgada",
    ),
    path(
        "reporte/<int:anio>/<int:mes>/",
        reporte_mensual_licencias,
        name="reporte_mensual_licencias",
    ),
    path(
        "planilla/<int:anio>/<int:mes>/",
        planilla_mensual,
        name="planilla_mensual",
    ),
    path(
        "planilla/<int:anio>/<int:mes>/csv/",
        planilla_mensual_csv,
        name="planilla_mensual_csv",
    ),
    path(
        "generador-disposiciones/",
        generador_disposiciones,
        name="generador_disposiciones",
    ),
     path(
        "<int:licencia_id>/resoluciones/",
        resoluciones_licencia,
        name="resoluciones_licencia",
    ),
    path(
        "resoluciones/<int:resolucion_id>/descargar/",
        descargar_resolucion,
        name="descargar_resolucion",
    ),
]