from django.contrib import admin

from .models import Disposicion, LicenciaArticulo, LicenciaOtorgada


@admin.register(LicenciaArticulo)
class LicenciaArticuloAdmin(admin.ModelAdmin):
    list_display = (
        'cod_licencia', 'articulo', 'tipo_licencia', 'sit_rev', 'clase',
        'categoria_informe', 'tope_cantidad', 'tope_unidad', 'tope_periodo', 'activo',
    )
    list_editable = ('categoria_informe',)
    search_fields = ('cod_licencia', 'articulo', 'tipo_licencia')
    list_filter = ('clase', 'sit_rev', 'categoria_informe', 'activo')


@admin.register(LicenciaOtorgada)
class LicenciaOtorgadaAdmin(admin.ModelAdmin):
    list_display = ('designacion', 'articulo', 'desde', 'hasta', 'sit_rev', 'anulada')
    list_filter = ('sit_rev', 'justifica', 'anulada')
    date_hierarchy = 'desde'
    search_fields = ('nro_formulario_papel', 'articulo__articulo', 'articulo__tipo_licencia')


@admin.register(Disposicion)
class DisposicionAdmin(admin.ModelAdmin):
    list_display = ('tipo', 'oficina_codigo', 'anio', 'numero', 'dni_beneficiario',
                    'periodo_mes', 'anulada')
    list_filter = ('tipo', 'anio', 'anulada')
    search_fields = ('dni_beneficiario',)
