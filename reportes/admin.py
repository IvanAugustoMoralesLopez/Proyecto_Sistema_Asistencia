from django.contrib import admin
from django.db import transaction

from asistencias.models import EventoAsistencia

from .auditoria import registrar_evento
from .models import ParametroSistema

CAMPOS_AUDITADOS = ("codigo_oficina", "nombre_oficina", "ciclo_lectivo")


@admin.register(ParametroSistema)
class ParametroSistemaAdmin(admin.ModelAdmin):
    list_display = ("codigo_oficina", "nombre_oficina", "ciclo_lectivo", "actualizado_en")
    readonly_fields = ("actualizado_por", "actualizado_en")

    def has_add_permission(self, request):
        return not ParametroSistema.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        """
        Editar desde el admin deja el mismo rastro que la pantalla de
        parámetros: completa actualizado_por y registra el evento en la
        bitácora (RF-20).
        """
        antes = None
        if change:
            # Foto previa tomada de la base: obj ya trae los valores nuevos.
            antes = ParametroSistema.objects.filter(pk=obj.pk).values(*CAMPOS_AUDITADOS).first()

        with transaction.atomic():
            obj.actualizado_por = request.user
            super().save_model(request, obj, form, change)
            registrar_evento(
                request.user,
                EventoAsistencia.Accion.PARAMETROS,
                motivo="Edición desde el admin",
                antes=antes,
                despues={campo: getattr(obj, campo) for campo in CAMPOS_AUDITADOS},
            )
