from django.contrib import admin

from .models import ParametroSistema


@admin.register(ParametroSistema)
class ParametroSistemaAdmin(admin.ModelAdmin):
    list_display = ("codigo_oficina", "nombre_oficina", "ciclo_lectivo", "actualizado_en")
    readonly_fields = ("actualizado_por", "actualizado_en")

    def has_add_permission(self, request):
        return not ParametroSistema.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
