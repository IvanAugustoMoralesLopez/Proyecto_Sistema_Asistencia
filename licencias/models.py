from django.db import models


class LicenciaOtorgada(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        APROBADA = "APROBADA", "Aprobada"
        RECHAZADA = "RECHAZADA", "Rechazada"

    designacion = models.ForeignKey(
        "personal.Designacion",
        on_delete=models.PROTECT,
        related_name="licencias_otorgadas",
    )
    disp_numero = models.CharField(max_length=20, blank=True)
    estado = models.CharField(
        max_length=12,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )
    desde = models.DateField()
    hasta = models.DateField()
    observaciones = models.TextField(blank=True)

    class Meta:
        db_table = "licencia_otorgada"
        ordering = ["-desde"]

    def __str__(self):
        return f"{self.designacion.persona.apellido_nombre} — {self.desde} a {self.hasta}"
