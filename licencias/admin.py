from django.contrib import admin

from .clasificacion import CategoriaSinPlanillaError, planilla_para_categoria
from .models import LicenciaArticulo, LicenciaOtorgada, RegistroBitacora, RenglonMensual


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


@admin.register(RenglonMensual)
class RenglonMensualAdmin(admin.ModelAdmin):
    """Consulta de la planilla mensual. Se edita desde su pantalla."""
    list_display = ('anio', 'mes', 'designacion', 'marca', 'desde', 'hasta',
                    'horas', 'planilla', 'cod_licencia', 'disp_numero')
    list_filter = ('anio', 'mes', 'planilla', 'marca')
    search_fields = ('designacion__persona__apellido_nombre', 'designacion__persona__dni')
    readonly_fields = ('creado_por', 'creado_en', 'actualizado_por', 'actualizado_en')

    def has_add_permission(self, request):
        return False


@admin.register(LicenciaOtorgada)
class LicenciaOtorgadaAdmin(admin.ModelAdmin):
    list_display = ('designacion', 'articulo', 'desde', 'hasta', 'sit_rev')
    list_filter = ('sit_rev', 'justifica')
    date_hierarchy = 'desde'
    # Obligatorio (admin.E040): otro admin referencia este modelo con
    # autocomplete_fields, y Django exige search_fields acá.
    search_fields = ('disp_numero', 'articulo__articulo', 'articulo__tipo_licencia')

@admin.register(RegistroBitacora)
class RegistroBitacoraAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'accion', 'descripcion')
    list_filter = ('accion', 'fecha')
    search_fields = ('descripcion',)
