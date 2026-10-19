from django.urls import path

from . import views

app_name = "asistencia"

urlpatterns = [
    path(
        "",
        views.registro_diario,
        name="registro_diario",
    ),
    path(
        "crear/",
        views.crear_asistencia,
        name="crear_asistencia",
    ),
    path(
        "editar/<int:pk>/",
        views.editar_asistencia,
        name="editar_asistencia",
    ),
    path(
        "historial/",
        views.historial,
        name="historial",
    ),
    path(
        "detalle/<int:pk>/",
        views.detalle_asistencia,
        name="detalle_asistencia",
    ),
    path(
        "validar/<int:pk>/",
        views.validar_registro,
        name="validar_registro",
    ),
    path(
        "cierres/",
        views.lista_cierres,
        name="lista_cierres",
    ),
    path(
        "cierres/confirmar/",
        views.confirmar_cierre,
        name="confirmar_cierre",
    ),
    path(
        "cierres/<int:anio>/<int:mes>/reabrir/",
        views.reapertura_mensual,
        name="reapertura_mensual",
    ),
    path(
        "sesion/liberar/",
        views.liberar_edicion,
        name="liberar_edicion",
    ),
    path(
        "sesion/renovar/",
        views.renovar_edicion,
        name="renovar_edicion",
    ),
]