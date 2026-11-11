from django.db import models

# Catálogo cerrado de marcas diarias (RF-08).
CODIGOS_MARCA = ("P", "I", "LIC", "LT", "PR")


class MarcaAsistencia(models.Model):
    codigo = models.CharField(max_length=12, unique=True)
    descripcion = models.CharField(max_length=100)
    # Cómo se nombra la marca en la carga diaria. `descripcion` es el término
    # administrativo (el que va a los informes en papel); `descripcion_simple`
    # es el que entiende quien carga todos los días.
    descripcion_simple = models.CharField(
        max_length=60,
        blank=True,
        help_text="Nombre en lenguaje llano para la pantalla de carga.",
    )
    ayuda = models.CharField(
        max_length=200,
        blank=True,
        help_text="Explicación corta que se muestra en «¿Qué significa cada opción?».",
    )
    computa_inasistencia = models.BooleanField(null=True, blank=True)
    requiere_observacion = models.BooleanField(default=False)
    requiere_horas = models.BooleanField(
        default=False,
        help_text="Si está activo, la carga diaria exige horas inasistidas mayores a cero.",
    )
    requiere_licencia = models.BooleanField(
        default=False,
        help_text="Si está activo, la carga diaria exige una licencia aprobada vinculada.",
    )
    activa = models.BooleanField(default=True)

    class Meta:
        db_table = "asistencia_marca"
        ordering = ["codigo"]

    @property
    def etiqueta(self):
        """Nombre a mostrar en pantalla: el llano si existe, si no el formal."""
        return self.descripcion_simple or self.descripcion

    @classmethod
    def vigentes(cls):
        """Marcas del catálogo cerrado que están activas."""
        return cls.objects.filter(activa=True, codigo__in=CODIGOS_MARCA)

    def __str__(self):
        return f"{self.codigo} — {self.descripcion}"
