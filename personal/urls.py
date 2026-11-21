from django.urls import path

from .views import (
    autocompletar_legajos,
    autocompletar_designaciones,
    catalogos_personal,
    gestion_legajos,
    nueva_designacion,
    editar_designacion,
    plantilla_importacion_csv,
)

app_name = "personal"

urlpatterns = [
    path("legajos/", gestion_legajos, name="gestion_legajos"),
    path(
        "designaciones/nueva/",
        nueva_designacion,
        name="nueva_designacion",
    ),
    path(
        "designaciones/<int:designacion_id>/editar/",
        editar_designacion,
        name="editar_designacion",
    ),
    path("catalogos/", catalogos_personal, name="catalogos"),
    path("legajos/autocompletar/", autocompletar_legajos, name="legajos_autocompletar"),
    path(
        "legajos/plantilla-csv/",
        plantilla_importacion_csv,
        name="plantilla_importacion_csv",
    ),
    path(
        "designaciones/autocompletar/",
        autocompletar_designaciones,
        name="designaciones_autocompletar",
    ),
]
