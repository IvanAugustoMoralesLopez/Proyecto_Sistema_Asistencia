from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models, transaction
from django.db.models import F, Q


class Persona(models.Model):
    dni = models.CharField(
        max_length=10,
        primary_key=True,
        validators=[
            RegexValidator(
                regex=r"^\d{7,10}$",
                message="El DNI debe contener entre 7 y 10 dígitos.",
            )
        ],
        verbose_name="DNI",
    )
    apellido_nombre = models.CharField(max_length=165)
    apellido = models.CharField(max_length=80, blank=True)
    nombres = models.CharField(max_length=80, blank=True)
    tipo_documento = models.CharField(max_length=10, default="DNI")
    sexo = models.CharField(
        max_length=1,
        choices=[("M", "Masculino"), ("F", "Femenino")],
        blank=True,
    )
    fecha_nacimiento = models.DateField(blank=True, null=True)
    estado_civil = models.CharField(max_length=20, blank=True)
    nacionalidad = models.CharField(max_length=40, blank=True)
    nro_dgi = models.CharField(max_length=20, blank=True)
    nro_dgr = models.CharField(max_length=20, blank=True)
    domicilio_calle = models.CharField(max_length=120, blank=True)
    barrio = models.CharField(max_length=80, blank=True)
    localidad = models.CharField(max_length=80, blank=True)
    codigo_postal = models.CharField(max_length=10, blank=True)
    provincia = models.CharField(max_length=60, blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    email = models.EmailField(max_length=120, blank=True)
    activa = models.BooleanField(default=True)

    class Meta:
        db_table = "personal_persona"
        ordering = ["apellido_nombre"]
        indexes = [
            models.Index(fields=["apellido_nombre"], name="ix_persona_apellido"),
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
    plan_estudio = models.CharField(max_length=60, blank=True)
    anio_plan = models.PositiveSmallIntegerField(blank=True, null=True)
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


class SituacionRevista(models.Model):
    codigo = models.CharField(max_length=20, primary_key=True)
    descripcion = models.CharField(max_length=80)
    activa = models.BooleanField(default=True)

    class Meta:
        db_table = "personal_situacion_revista"
        ordering = ["descripcion"]
        verbose_name = "situación de revista"
        verbose_name_plural = "situaciones de revista"

    def __str__(self):
        return self.descripcion


class UnidadEducativa(models.Model):
    numero = models.CharField(max_length=20, blank=True)
    descripcion = models.CharField(max_length=120, blank=True)
    codigo_oficina = models.CharField(max_length=10, blank=True)
    codigo_anexo = models.CharField(max_length=10, blank=True)
    nivel_modalidad = models.CharField(max_length=60, blank=True)
    categoria = models.CharField(max_length=20, blank=True)
    zona = models.CharField(max_length=30, blank=True)
    localidad_paraje = models.CharField(max_length=80, blank=True)
    activa = models.BooleanField(default=True)

    class Meta:
        db_table = "personal_unidad_educativa"
        ordering = ["descripcion", "numero"]
        verbose_name = "unidad educativa"
        verbose_name_plural = "unidades educativas"

    def __str__(self):
        return self.descripcion or self.numero or str(self.pk)


class Especialidad(models.Model):
    titulo = models.CharField(max_length=120, unique=True)
    activa = models.BooleanField(default=True)

    class Meta:
        db_table = "personal_especialidad_catalogo"
        ordering = ["titulo"]

    def __str__(self):
        return self.titulo


class Motivo(models.Model):
    codigo = models.CharField(max_length=5, unique=True)
    descripcion = models.CharField(max_length=200)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "personal_motivo"
        ordering = ["descripcion"]

    def __str__(self):
        return self.descripcion


class Designacion(models.Model):
    class Situacion(models.TextChoices):
        TITULAR = "TIT", "Titular"
        INTERINO = "INT", "Interino"
        SUPLENTE = "SUP", "Suplente"

    class TipoNorma(models.TextChoices):
        RESOLUCION = "Resolución", "Resolución"
        DISPOSICION = "Disposición", "Disposición"

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
    unidad_educativa = models.ForeignKey(
        UnidadEducativa,
        on_delete=models.PROTECT,
        related_name="designaciones",
        blank=True,
        null=True,
    )
    especialidad = models.ForeignKey(
        Especialidad,
        on_delete=models.PROTECT,
        related_name="designaciones",
        blank=True,
        null=True,
    )
    reemplaza = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="reemplazos",
        blank=True,
        null=True,
    )
    situacion_revista = models.CharField(
        max_length=30,
        choices=Situacion.choices,
        blank=True,
    )
    anio_curso = models.CharField(max_length=10, blank=True)
    division_seccion = models.CharField(max_length=20, blank=True)
    turno = models.CharField(max_length=20, blank=True)
    hs_catedra = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        validators=[MaxValueValidator(255)],
    )
    jornada = models.CharField(max_length=30, blank=True)
    disp_alta_nro = models.CharField(max_length=20, blank=True)
    sello_regional_as = models.CharField(max_length=30, blank=True)
    motivo = models.ForeignKey(
        Motivo,
        on_delete=models.PROTECT,
        related_name="designaciones",
        blank=True,
        null=True,
    )
    norma_tipo = models.CharField(
        max_length=30,
        choices=TipoNorma.choices,
        blank=True,
    )
    norma_numero = models.CharField(max_length=30, blank=True)
    norma_anio = models.PositiveSmallIntegerField(blank=True, null=True)
    organismo_emisor = models.CharField(max_length=120, blank=True)
    desde = models.DateField()
    hasta = models.DateField(blank=True, null=True)
    pof = models.CharField(max_length=30, blank=True)
    anio_pof = models.PositiveSmallIntegerField(blank=True, null=True)
    novedad = models.CharField(max_length=40, blank=True)
    activo = models.BooleanField(default=True)
    observaciones = models.TextField(blank=True)

    class Meta:
        db_table = "personal_designacion"
        ordering = ["persona__apellido_nombre", "desde"]
        constraints = [
            models.CheckConstraint(
                condition=Q(hasta__isnull=True) | Q(hasta__gte=F("desde")),
                name="ck_designacion_fechas",
            ),
        ]
        indexes = [
            models.Index(
                fields=["persona", "activo"],
                name="ix_designacion_persona_activo",
            ),
            models.Index(
                fields=["cargo", "activo"],
                name="ix_designacion_cargo_activo",
            ),
            models.Index(fields=["desde", "hasta"], name="ix_desig_vigencia"),
        ]

    @property
    def sitacion_revista(self):
        return self.situacion_revista

    def vigente_en(self, fecha):
        return (
            self.activo
            and self.desde <= fecha
            and (self.hasta is None or fecha <= self.hasta)
        )

    def save(self, *args, **kwargs):
        with transaction.atomic():
            es_nueva = self._state.adding
            anterior = None
            if not es_nueva:
                campos_historial = (
                    "situacion_revista",
                    "desde",
                    "hasta",
                    "activo",
                    "cargo_id",
                    "espacio_curricular_id",
                    "hs_catedra",
                    "turno",
                    "norma_tipo",
                    "norma_numero",
                    "norma_anio",
                    "organismo_emisor",
                    "pof",
                    "anio_pof",
                    "observaciones",
                )
                anterior = (
                    type(self).objects.filter(pk=self.pk)
                    .values(*campos_historial)
                    .first()
                )

            super().save(*args, **kwargs)

            actual = {
                "situacion_revista": self.situacion_revista,
                "desde": self.desde,
                "hasta": self.hasta,
                "activo": self.activo,
                "cargo_id": self.cargo_id,
                "espacio_curricular_id": self.espacio_curricular_id,
                "hs_catedra": self.hs_catedra,
                "turno": self.turno,
                "norma_tipo": self.norma_tipo,
                "norma_numero": self.norma_numero,
                "norma_anio": self.norma_anio,
                "organismo_emisor": self.organismo_emisor,
                "pof": self.pof,
                "anio_pof": self.anio_pof,
                "observaciones": self.observaciones,
            }
            if anterior is not None and anterior == actual:
                return

            if es_nueva:
                accion = HistorialDesignacion.Accion.ALTA
            elif anterior and anterior["activo"] and not self.activo:
                accion = HistorialDesignacion.Accion.BAJA
            elif (
                anterior
                and anterior["situacion_revista"] != self.situacion_revista
            ):
                accion = HistorialDesignacion.Accion.CAMBIO_SITUACION
            elif anterior and anterior["desde"] != self.desde:
                accion = HistorialDesignacion.Accion.TOMA_POSESION
            elif anterior:
                accion = HistorialDesignacion.Accion.MODIFICACION
            else:
                return

            HistorialDesignacion.objects.create(
                designacion=self,
                accion=accion,
                situacion_revista=self.situacion_revista,
                cargo_id=self.cargo_id,
                espacio_curricular_id=self.espacio_curricular_id,
                desde=self.desde,
                hasta=self.hasta,
                activo=self.activo,
                datos_anteriores=_serializar_valores(anterior),
                datos_nuevos=_serializar_valores(actual),
            )

    def __str__(self):
        return (
            f"{self.persona.apellido_nombre} - "
            f"{self.cargo.descripcion} - "
            f"{self.desde}"
        )


class Horario(models.Model):
    class Dia(models.TextChoices):
        LUNES = "LUN", "Lunes"
        MARTES = "MAR", "Martes"
        MIERCOLES = "MIE", "Miércoles"
        JUEVES = "JUE", "Jueves"
        VIERNES = "VIE", "Viernes"

    designacion = models.ForeignKey(
        Designacion,
        on_delete=models.CASCADE,
        related_name="horarios",
    )
    dia = models.CharField(max_length=3, choices=Dia.choices)
    horas_catedra = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(255)]
    )
    hora_inicio = models.TimeField(blank=True, null=True)
    hora_fin = models.TimeField(blank=True, null=True)

    class Meta:
        db_table = "personal_horario"
        ordering = ["dia"]
        constraints = [
            models.UniqueConstraint(
                fields=["designacion", "dia"],
                name="uq_horario_desig_dia",
            ),
            models.CheckConstraint(
                condition=(
                    Q(hora_inicio__isnull=True)
                    | Q(hora_fin__isnull=True)
                    | Q(hora_fin__gt=F("hora_inicio"))
                ),
                name="ck_horario_horas",
            ),
        ]

    def __str__(self):
        return f"{self.get_dia_display()}: {self.horas_catedra} horas"


class HistorialDesignacion(models.Model):
    class Accion(models.TextChoices):
        ALTA = "ALTA", "Alta"
        MODIFICACION = "MODIFICACION", "Modificación"
        BAJA = "BAJA", "Baja"
        TOMA_POSESION = "TOMA_POSESION", "Toma de posesión"
        CAMBIO_SITUACION = "CAMBIO_SITUACION", "Cambio de situación"

    designacion = models.ForeignKey(
        Designacion,
        on_delete=models.PROTECT,
        related_name="historial",
    )
    accion = models.CharField(max_length=20, choices=Accion.choices)
    fecha_hora = models.DateTimeField(auto_now_add=True)
    situacion_revista = models.CharField(max_length=20, blank=True)
    cargo_id = models.CharField(max_length=10)
    espacio_curricular_id = models.PositiveBigIntegerField(blank=True, null=True)
    desde = models.DateField()
    hasta = models.DateField(blank=True, null=True)
    activo = models.BooleanField()
    datos_anteriores = models.JSONField(default=dict)
    datos_nuevos = models.JSONField(default=dict)

    class Meta:
        db_table = "personal_historial_designacion"
        ordering = ["-fecha_hora", "-pk"]
        verbose_name = "historial de designación"
        verbose_name_plural = "historiales de designación"


class ImportacionPersonalError(models.Model):
    archivo = models.CharField(max_length=255)
    numero_fila = models.PositiveIntegerField()
    dni_texto = models.CharField(max_length=20, blank=True)
    motivo_error = models.CharField(max_length=255)
    fila_original = models.JSONField(default=dict)
    fecha_hora = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "personal_importacion_error"
        ordering = ["-fecha_hora", "numero_fila"]
        verbose_name = "error de importación de personal"
        verbose_name_plural = "errores de importación de personal"

    def __str__(self):
        return f"{self.archivo}, fila {self.numero_fila}: {self.motivo_error}"


def _serializar_valores(valores):
    if not valores:
        return {}
    return {
        clave: valor.isoformat() if hasattr(valor, "isoformat") else valor
        for clave, valor in valores.items()
    }
