
from django.contrib import admin

from .models import LicenciaOtorgada


@admin.register(LicenciaOtorgada)
class LicenciaOtorgadaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "designacion",
        "disp_numero",
        "desde",
        "hasta",
    )

    search_fields = (
        "disp_numero",
        "designacion__persona__dni",
        "designacion__persona__apellido_nombre",
    )

    list_filter = (
        "desde",
        "hasta",
    )

    autocomplete_fields = (
        "designacion",
    )
