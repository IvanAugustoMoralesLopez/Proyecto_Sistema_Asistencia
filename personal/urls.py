from django.urls import path

from .views import gestion_legajos, nueva_designacion

app_name = "personal"

urlpatterns = [
    path("legajos/", gestion_legajos, name="gestion_legajos"),
    path(
        "designaciones/nueva/",
        nueva_designacion,
        name="nueva_designacion",
    ),
]
