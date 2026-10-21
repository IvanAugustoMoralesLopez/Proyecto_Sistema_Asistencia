from django.urls import path

from .views import gestion_legajos

app_name = "personal"

urlpatterns = [
    path("legajos/", gestion_legajos, name="gestion_legajos"),
]
