
from django.contrib import admin

from .models import (
    MarcaAsistencia,
    CierreMensual,
    RegistroAsistencia,
    EventoAsistencia,
    SesionEdicion,
    ControlConcurrencia,
    DiaNoLaborable,
)


@admin.register(MarcaAsistencia)
class MarcaAsistenciaAdmin(admin.ModelAdmin):
    list_display = (
        "codigo",
        "descripcion",
        "computa_inasistencia",
        "requiere_observacion",
        "requiere_horas",
        "requiere_licencia",
        "activa",
    )
    search_fields = ("codigo", "descripcion")
    list_filter = (
        "activa",
        "computa_inasistencia",
        "requiere_observacion",
        "requiere_horas",
        "requiere_licencia",
    )


@admin.register(DiaNoLaborable)
class DiaNoLaborableAdmin(admin.ModelAdmin):
    list_display = ("fecha", "tipo", "descripcion")
    list_filter = ("tipo",)
    search_fields = ("descripcion",)
    date_hierarchy = "fecha"


@admin.register(RegistroAsistencia)
class RegistroAsistenciaAdmin(admin.ModelAdmin):
    list_display = (
        "fecha",
        "designacion",
        "marca",
        "estado_registro",
        "actualizado_por",
        "actualizado_en",
    )
    list_filter = (
        "estado_registro",
        "marca",
        "fecha",
    )
    search_fields = (
        "designacion__persona__dni",
        "designacion__persona__apellido_nombre",
    )
    autocomplete_fields = (
        "designacion",
        "marca",
        "licencia",
    )
    readonly_fields = (
        "creado_en",
        "actualizado_en",
        "creado_por",
        "actualizado_por",
    )
    date_hierarchy = "fecha"

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CierreMensual)
class CierreMensualAdmin(admin.ModelAdmin):
    list_display = (
        "anio",
        "mes",
        "estado",
        "cerrado_por",
        "cerrado_en",
        "reabierto_por",
        "version",
    )
    list_filter = ("estado", "anio")
    readonly_fields = (
        "cerrado_por",
        "cerrado_en",
        "reabierto_por",
        "reabierto_en",
        "motivo_reapertura",
        "version",
    )

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(EventoAsistencia)
class EventoAsistenciaAdmin(admin.ModelAdmin):
    list_display = (
        "creado_en",
        "usuario",
        "accion",
        "asistencia",
        "cierre",
    )
    list_filter = ("accion", "creado_en")
    search_fields = (
        "usuario__username",
        "motivo",
    )
    readonly_fields = (
        "asistencia",
        "cierre",
        "usuario",
        "accion",
        "motivo",
        "antes",
        "despues",
        "creado_en",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SesionEdicion)
class SesionEdicionAdmin(admin.ModelAdmin):
    list_display = (
        "usuario",
        "creada_en",
        "heartbeat_en",
        "expira_en",
        "activa",
    )
    list_filter = ("activa",)
    readonly_fields = (
        "token",
        "usuario",
        "creada_en",
        "heartbeat_en",
        "expira_en",
    )


@admin.register(ControlConcurrencia)
class ControlConcurrenciaAdmin(admin.ModelAdmin):
    list_display = ("id", "actualizado_en")
    readonly_fields = ("id", "actualizado_en")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
