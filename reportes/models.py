from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


def anio_actual():
    return timezone.localdate().year


class ParametroSistema(models.Model):
    """
    Parámetros globales del sistema (RF-21).

    Es una tabla de una sola fila (pk=1). El resto de los módulos debe
    leerla con ParametroSistema.obtener() en lugar de fijar valores a mano.
    """

    codigo_oficina = models.CharField(
        "Código de oficina",
        max_length=10,
        default="1452",
    )
    nombre_oficina = models.CharField(
        "Nombre de la oficina",
        max_length=120,
        default="IESETyFP",
    )
    ciclo_lectivo = models.PositiveSmallIntegerField(
        "Ciclo lectivo",
        default=anio_actual,
        validators=[MinValueValidator(2000), MaxValueValidator(2100)],
    )
    actualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="parametros_actualizados",
    )
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "reportes_parametro_sistema"
        verbose_name = "Parámetro del sistema"
        verbose_name_plural = "Parámetros del sistema"
        # Permisos de la Pantalla 4 (se asignan a los roles en roles.py).
        permissions = [
            ("gestionar_parametros", "Puede modificar los parámetros del sistema"),
            ("ver_bitacora", "Puede consultar la bitácora de auditoría"),
            ("gestionar_usuarios", "Puede administrar usuarios y roles"),
            ("consultar_licencias", "Puede usar el módulo de consultas de licencias"),
        ]

    def save(self, *args, **kwargs):
        self.pk = 1  # una única fila de configuración
        super().save(*args, **kwargs)

    @classmethod
    def obtener(cls):
        parametros, _ = cls.objects.get_or_create(pk=1)
        return parametros

    def __str__(self):
        return f"Oficina {self.codigo_oficina} - {self.nombre_oficina} ({self.ciclo_lectivo})"
