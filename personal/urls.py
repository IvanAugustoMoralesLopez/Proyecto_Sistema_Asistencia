from django.urls import path

from .views import (
    autocompletar_legajos,
    autocompletar_designaciones,
    catalogos_personal,
    gestion_legajos,
    nueva_designacion,
    editar_designacion,
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
        "designaciones/autocompletar/",
        autocompletar_designaciones,
        name="designaciones_autocompletar",
    ),
]
