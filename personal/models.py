from django.db import models
from django.core.validators import MinLengthValidator
from django.db.models import Q

class Persona(models.Model):
    dni = models.CharField(
        max_length=8,
        unique=True,
        primary_key=True,
        validators=[MinLengthValidator(8)],
        verbose_name="DNI",
    )
    apellido_nombre = models.CharField(max_length=120)
    sexo = models.CharField(max_length=1, choices=[("M", "Masculino"), ("F", "Femenino")])
    activa = models.BooleanField(default=True)

    class Meta:
        db_table = "personal_persona"
        ordering = ["apellido_nombre"]
        indexes = [
            models.Index(
                fields=["apellido_nombre"],
                name="ix_persona_apellido",

            ),
        ]

    def __str__(self):
        return f"{self.apellido_nombre} ({self.dni})"


class Cargo(models.Model):
        codigo = models.CharField(max_length=10, primary_key=True)
        descripcion = models.CharField(max_length=120)
        es_docente = models.BooleanField(default=True)
        activo = models.BooleanField(default=True)

        class Meta:
            db_table = "personal_cargo"
            ordering = ["descripcion"]

        def __str__(self):
            return self.descripcion

class Carrera(models.Model):
        nombre = models.CharField(max_length=120, unique=True)
        plan_estudio = models.CharField(max_length=10, blank=True)
        anio_plan = models.PositiveBigIntegerField(blank=True, null=True)
        activa = models.BooleanField(default=True)

        class Meta:
            db_table = "personal_carrera"
            ordering = ["nombre"]

        def __str__(self):
            return self.nombre

class EspacioCurricular(models.Model):
        nombre = models.CharField(max_length=120)
        carrera = models.ForeignKey(
            Carrera,
            on_delete=models.PROTECT,
            related_name="espacios_curriculares",
        )
        activo = models.BooleanField(default=True)

        class Meta:
            db_table = "personal_espacio_curricular"
            ordering = ["carrera__nombre", "nombre"]
            constraints = [
                 models.UniqueConstraint(
                    fields=["nombre", "carrera"],
                    name="uq_espacio_carrera_mnombre",
                 ),
            ]

        def __str__(self):
            return f"{self.nombre} ({self.carrera.nombre})"

class Designacion(models.Model):
    persona = models.ForeignKey(
         Persona,
         on_delete=models.PROTECT,
         related_name="designaciones",
    )
    cargo = models.ForeignKey(
         Cargo,
         on_delete=models.PROTECT,
         related_name="designaciones",
    )
    espacio_curricular = models.ForeignKey(
         EspacioCurricular,
         on_delete=models.PROTECT,
         related_name="designaciones",
         blank=True,
         null=True,
    )
    sitacion_revista = models.Charfield(
         max_length=30,
         blank=True,
    )
    norma_tipo = models.CharField(max_length=30, blank=True)
    norma_numero = models.CharField(max_length=30, blank=True)
    norma_anio = models.PositiveBigIntegerField(blank=True, null=True)
    organismo_emisor = models.CharField(max_length=120, blank=True)
    desde = models.DateField()
    hasta = models.DateField(blank=True, null=True)
    activo = models.BooleanField(default=True)
    observaciones = models.TextField(blank=True)

    class Meta:
        db_table = "personal_designacion"
        ordering = ["persona__apellido_nombre", "desde"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(hasta__isnull=True) | Q(hasta__gte=models.F("desde"))),
                name="ck_designacion_fechas",

                ),
            ]
        indexes = [
             models.Index(
                  fields = ["persona", "activo"],
                  name = "ix_designacion_persona_activo",
             ),
             models.Index(
                  fields = ["cargo", "activo"],
                    name = "ix_designacion_cargo_activo",
             ),
        ]

    def __str__(self):
         return (
              f"{self.persona.apellido_nombre} - "
              f"{self.cargo.descripcion} - "
              f"{self.desde}"
         )