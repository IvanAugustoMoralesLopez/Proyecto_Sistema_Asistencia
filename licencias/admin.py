from django.contrib import admin
from .models import LicenciaArticulo, LicenciaOtorgada, RegistroBitacora

@admin.register(LicenciaArticulo)
class LicenciaArticuloAdmin(admin.ModelAdmin):
    list_display = ('cod_licencia', 'articulo', 'tipo_licencia', 'sit_rev', 'clase', 'tope_dias_anual')
    list_editable = ('tope_dias_anual',)
    search_fields = ('cod_licencia', 'articulo', 'tipo_licencia')
    list_filter = ('clase', 'sit_rev', 'categoria_informe')

@admin.register(LicenciaOtorgada)
class LicenciaOtorgadaAdmin(admin.ModelAdmin):
    list_display = ('designacion', 'articulo', 'desde', 'hasta', 'sit_rev')
    list_filter = ('sit_rev', 'justifica')
    date_hierarchy = 'desde'
    # Esta línea soluciona el error E040
    search_fields = ('disp_numero', 'articulo__articulo', 'articulo__tipo_licencia') 

@admin.register(RegistroBitacora)
class RegistroBitacoraAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'accion', 'descripcion')
    list_filter = ('accion', 'fecha')
    search_fields = ('descripcion',)