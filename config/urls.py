"""
URL configuration for sistema_asistencia project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path

from django.views.generic import TemplateView

urlpatterns = [
    path('admin/', admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("asistencia/", include("asistencias.urls")),
    path("personal/", include("personal.urls")),
    path("reportes/", include("reportes.urls")),

    # Pantallas de prueba (después las reemplaza backend con sus vistas)
    path("pantallas/personal/", TemplateView.as_view(template_name="pantallas/datos_personal.html"), name="pantalla_personal"),
    path("pantallas/licencias/", TemplateView.as_view(template_name="pantallas/codigos_licencia.html"), name="pantalla_licencias"),
    path("pantallas/informe/", TemplateView.as_view(template_name="pantallas/informe_licencias.html"), name="pantalla_informe"),
    path("pantallas/ingreso-egreso/", TemplateView.as_view(template_name="pantallas/ingreso_egreso.html"), name="pantalla_ingreso_egreso"),
    path("", TemplateView.as_view(template_name="pantallas/datos_personal.html")),
]
