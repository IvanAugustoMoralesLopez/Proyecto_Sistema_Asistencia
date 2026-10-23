from django.contrib import admin

from .models import (
    Cargo,
    Carrera,
    Designacion,
    Especialidad,
    EspacioCurricular,
    HistorialDesignacion,
    Horario,
    ImportacionPersonalError,
    Motivo,
    Persona,
    SituacionRevista,
    UnidadEducativa,
)


@admin.register(Persona)
class PersonaAdmin(admin.ModelAdmin):
    list_display = ("dni", "apellido_nombre", "telefono", "email", "activa")
    search_fields = ("dni", "apellido_nombre", "apellido", "nombres", "email")
    list_filter = ("activa", "sexo", "localidad")
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
    list_filter = ("activo", "carrera")
    autocomplete_fields = ("carrera",)


@admin.register(SituacionRevista)
class SituacionRevistaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "descripcion", "activa")
    search_fields = ("codigo", "descripcion")
    list_filter = ("activa",)


@admin.register(UnidadEducativa)
class UnidadEducativaAdmin(admin.ModelAdmin):
    list_display = ("numero", "descripcion", "localidad_paraje", "activa")
    search_fields = ("numero", "descripcion", "codigo_oficina", "localidad_paraje")
    list_filter = ("activa", "nivel_modalidad", "zona")


@admin.register(Especialidad)
class EspecialidadAdmin(admin.ModelAdmin):
    list_display = ("titulo", "activa")
    search_fields = ("titulo",)
    list_filter = ("activa",)


@admin.register(Motivo)
class MotivoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "descripcion", "activo")
    search_fields = ("codigo", "descripcion")
    list_filter = ("activo",)


class HorarioInline(admin.TabularInline):
    model = Horario
    extra = 0


class HistorialDesignacionInline(admin.TabularInline):
    model = HistorialDesignacion
    extra = 0
    can_delete = False
    fields = (
        "fecha_hora",
        "accion",
        "situacion_revista",
        "desde",
        "hasta",
        "activo",
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Designacion)
class DesignacionAdmin(admin.ModelAdmin):
    list_display = (
        "persona",
        "cargo",
        "espacio_curricular",
        "situacion_revista",
        "desde",
        "hasta",
        "activo",
    )
    search_fields = (
        "persona__dni",
        "persona__apellido_nombre",
        "cargo__descripcion",
        "espacio_curricular__nombre",
    )
    list_filter = ("cargo", "situacion_revista", "desde", "hasta", "activo")
    autocomplete_fields = (
        "persona",
        "cargo",
        "espacio_curricular",
        "unidad_educativa",
        "especialidad",
        "motivo",
    )
    date_hierarchy = "desde"
    inlines = (HorarioInline, HistorialDesignacionInline)


@admin.register(ImportacionPersonalError)
class ImportacionPersonalErrorAdmin(admin.ModelAdmin):
    list_display = ("fecha_hora", "archivo", "numero_fila", "dni_texto", "motivo_error")
    search_fields = ("archivo", "dni_texto", "motivo_error")
    list_filter = ("fecha_hora",)
    readonly_fields = (
        "archivo",
        "numero_fila",
        "dni_texto",
        "motivo_error",
        "fila_original",
        "fecha_hora",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
