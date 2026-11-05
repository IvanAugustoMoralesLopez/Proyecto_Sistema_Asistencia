from django.conf import settings
from django.db import models

from .cierres import CierreDiario, CierreMensual
from .registro import RegistroAsistencia


class EventoAsistencia(models.Model):
    class Accion(models.TextChoices):
        CREAR = "CREAR", "Crear"
        EDITAR = "EDITAR", "Editar"
        VALIDAR = "VALIDAR", "Validar"
        RECEPCIONAR = "RECEPCIONAR", "Recepcionar formulario"
        CERRAR_DIA = "CERRAR_DIA", "Cerrar jornada"
        CERRAR = "CERRAR", "Cerrar período"
        REABRIR = "REABRIR", "Reabrir período"
        PARAMETROS = "PARAMETROS", "Modificar parámetros"
        USUARIO_ALTA = "USUARIO_ALTA", "Alta de usuario"
        USUARIO_EDITAR = "USUARIO_EDITAR", "Modificar usuario"

    asistencia = models.ForeignKey(
        RegistroAsistencia,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="eventos",
    )
    cierre = models.ForeignKey(
        CierreMensual,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="eventos",
    )
    cierre_diario = models.ForeignKey(
        CierreDiario,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="eventos",
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.PROTECT,
        related_name="eventos_asistencia",
    )
    accion = models.CharField(max_length=20, choices=Accion.choices)
    motivo = models.CharField(max_length=500, blank=True)
    antes = models.JSONField(null=True, blank=True)
    despues = models.JSONField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "asistencia_evento"
        ordering = ["-creado_en"]
        indexes = [
            models.Index(
                fields=["asistencia", "creado_en"],
                name="ix_evento_asist_fecha",
            ),
            models.Index(
                fields=["usuario", "creado_en"],
                name="ix_evento_usr_fecha",
            ),
        ]

    def __str__(self):
        return f"{self.accion} — {self.creado_en:%Y-%m-%d %H:%M}"
