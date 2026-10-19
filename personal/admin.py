from django.contrib import admin
from .models import Persona, Cargo, Carrera, EspacioCurricular, Designacion

#Mantenimiento: el panel administrativo es útil para cargar catálogos y corregir datos de referencia.
#No debe ser la vía habitual para editar asistencias, 
#porque las reglas de cierre y auditoría deben pasar por los servicios de la aplicación.
@admin.register(Persona)
class PersonaAdmin(admin.ModelAdmin):
    list_display = ("dni", "apellido_nombre", "activa")
    search_fields = ("dni", "apellido_nombre")
    list_filter = ("activa",)
    ordering = ("apellido_nombre",)

@admin.register(Cargo)
class CargoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "descripcion", "es_docente", "activo")
    search_fields = ("codigo", "descripcion")
    list_filter = ("es_docente", "activo")


@admin.register(Carrera)
class CarreraAdmin(admin.ModelAdmin):
    list_display = ("nombre", "plan_estudio", "anio_plan", "activa")
    search_fields = ("nombre", "plan_estudio")
    list_filter = ("activa",)

@admin.register(EspacioCurricular)
class EspacioCurricularAdmin(admin.ModelAdmin):
    list_display = ("nombre", "carrera", "activo")
    search_fields = ("nombre", "carrera__nombre")
    list_filter = ("activo",)

@admin.register(Designacion)
class DesignacionAdmin(admin.ModelAdmin):
    list_display = ("persona", "cargo", "espacio_curricular", "desde", "hasta", "activo")
    search_fields = ("Persona__dni", "persona__apellido_nombre", "cargo__descripcion", "espacio_curricular__nombre")
    list_filter = ("cargo", "desde", "hasta", "activo")
    autocomplete_fields = ("persona", "cargo", "espacio_curricular")
    date_hierarchy = "desde"