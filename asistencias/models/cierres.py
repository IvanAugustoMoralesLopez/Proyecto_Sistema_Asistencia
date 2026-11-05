from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class CierreMensual(models.Model):
    class Estado(models.TextChoices):
        ABIERTO = "ABIERTO", "Abierto"
        CERRADO = "CERRADO", "Cerrado"

    anio = models.PositiveSmallIntegerField()
    mes = models.PositiveSmallIntegerField()
    estado = models.CharField(
        max_length=12,
        choices=Estado.choices,
        default=Estado.ABIERTO,
    )
    cerrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="cierres_asistencia",
    )
    cerrado_en = models.DateTimeField(null=True, blank=True)
    reabierto_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reaperturas_asistencia",
    )
    reabierto_en = models.DateTimeField(null=True, blank=True)
    motivo_reapertura = models.CharField(max_length=500, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "asistencia_cierre_mensual"
        ordering = ["-anio", "-mes"]
        permissions = [
            ("cerrar_periodo", "Puede cerrar períodos mensuales"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["anio", "mes"],
                name="uq_asist_cierre_periodo",
            ),
            models.CheckConstraint(
                condition=Q(mes__gte=1, mes__lte=12),
                name="ck_asist_cierre_mes",
            ),
        ]

    def __str__(self):
        return f"{self.anio}-{self.mes:02d} ({self.estado})"


class CierreDiario(models.Model):
    """
    Jornada cerrada (RN-06): una vez cerrada, modificar sus registros
    requiere autorización de Secretaría o Subsecretaría.
    """
    fecha = models.DateField(unique=True)
    cerrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cierres_diarios",
    )
    cerrado_en = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "asistencia_cierre_diario"
        ordering = ["-fecha"]
        permissions = [
            ("cerrar_jornada", "Puede cerrar la jornada diaria"),
        ]

    def __str__(self):
        return f"Jornada {self.fecha:%d/%m/%Y} cerrada"
