from django.urls import path

from .views import nueva_licencia_otorgada

app_name = "licencias"

urlpatterns = [
    path(
        "nueva/",
        nueva_licencia_otorgada,
        name="nueva_licencia_otorgada",
    ),
]