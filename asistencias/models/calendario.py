from django.db import models


class DiaNoLaborable(models.Model):
    class Tipo(models.TextChoices):
        FERIADO = "FERIADO", "Feriado"
        ASUETO = "ASUETO", "Asueto"
        INHABIL = "INHABIL", "Día inhábil"

    fecha = models.DateField(unique=True)
    tipo = models.CharField(
        max_length=10,
        choices=Tipo.choices,
        default=Tipo.FERIADO,
    )
    descripcion = models.CharField(max_length=150, blank=True)

    class Meta:
        db_table = "asistencia_dia_no_laborable"
        ordering = ["fecha"]

    def __str__(self):
        return f"{self.fecha} — {self.get_tipo_display()}"
