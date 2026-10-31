from django.contrib import admin

from .clasificacion import CategoriaSinPlanillaError, planilla_para_categoria
from .models import LicenciaArticulo, LicenciaOtorgada, RegistroBitacora


@admin.register(LicenciaArticulo)
class LicenciaArticuloAdmin(admin.ModelAdmin):
    list_display = (
        'cod_licencia', 'articulo', 'tipo_licencia', 'sit_rev', 'clase',
        'categoria_informe', 'planilla', 'tope_dias_anual',
    )
    # Permite reclasificar rápido los artículos que quedaron con una categoría vieja.
    list_editable = ('categoria_informe', 'tope_dias_anual')
    search_fields = ('cod_licencia', 'articulo', 'tipo_licencia')
    list_filter = ('clase', 'sit_rev', 'categoria_informe')

    @admin.display(description='Planilla')
    def planilla(self, obj):
        try:
            return planilla_para_categoria(obj.categoria_informe)
        except CategoriaSinPlanillaError:
            return '⚠ Sin clasificar'


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
