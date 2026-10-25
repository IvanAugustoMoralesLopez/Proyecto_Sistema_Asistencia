from django.urls import path

from . import views

app_name = "reportes"

urlpatterns = [
    path("consultas/", views.consultas, name="consultas"),
    path("bitacora/", views.bitacora, name="bitacora"),
    path("parametros/", views.parametros, name="parametros"),
    path("usuarios/", views.usuarios, name="usuarios"),
    path("usuarios/nuevo/", views.usuario_crear, name="usuario_crear"),
    path("usuarios/<int:pk>/", views.usuario_editar, name="usuario_editar"),
]
