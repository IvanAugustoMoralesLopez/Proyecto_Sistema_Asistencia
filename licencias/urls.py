
from django.urls import path

from .views import (
    nueva_licencia_otorgada,
    listado_licencias_otorgadas,
    editar_licencia_otorgada,
)

app_name = "licencias"

urlpatterns = [
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
]
