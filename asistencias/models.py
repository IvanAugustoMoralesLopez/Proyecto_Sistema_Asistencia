import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class MarcaAsistencia(models.Model):
    codigo = models.CharField(max_length=12, unique=True)
    descripcion = models.CharField(max_length=100)
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

    def __str__(self):
        return f"{self.codigo} — {self.descripcion}"


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


class RegistroAsistencia(models.Model):
    class Estado(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador"
        VALIDADO = "VALIDADO", "Validado"

    designacion = models.ForeignKey(
        "personal.Designacion",
        on_delete=models.PROTECT,
        related_name="registros_asistencia",
    )
    fecha = models.DateField()
    marca = models.ForeignKey(
        MarcaAsistencia,
        on_delete=models.PROTECT,
        related_name="registros",
    )
    estado_registro = models.CharField(
        max_length=12,
        choices=Estado.choices,
        default=Estado.BORRADOR,
    )
    horas_inasistidas = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("0"),
        blank=True,
        validators=[MinValueValidator(0)],
    )
    licencia = models.ForeignKey(
        "licencias.LicenciaOtorgada",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="asistencias_relacionadas",
    )
    observaciones = models.TextField(blank=True)

    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.PROTECT,
        related_name="asistencias_creadas",
    )
    actualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.PROTECT,
        related_name="asistencias_actualizadas",
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "asistencia_registro"
        ordering = ["-fecha", "designacion_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["designacion", "fecha"],
                name="uq_asist_designacion_fecha",
            ),
            models.CheckConstraint(
                condition=Q(horas_inasistidas__gte=0),
                name="ck_asist_horas_no_negativas",
            ),
        ]
        indexes = [
            models.Index(
                fields=["fecha", "marca"],
                name="ix_asist_fecha_marca",
            ),
            models.Index(
                fields=["designacion", "fecha"],
                name="ix_asist_design_fecha",
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.licencia_id
            and self.designacion_id
            and self.licencia.designacion_id != self.designacion_id
        ):
            from django.core.exceptions import ValidationError

            raise ValidationError({
                "licencia": (
                    "La licencia no pertenece a la designación seleccionada."
                )
            })

        if (
            self.licencia_id
            and self.fecha
            and not self.licencia.desde <= self.fecha <= self.licencia.hasta
        ):
            from django.core.exceptions import ValidationError

            raise ValidationError({
                "licencia": "La fecha no está comprendida en la licencia."
            })

    def __str__(self):
        return f"{self.designacion_id} — {self.fecha}"


class EventoAsistencia(models.Model):
    class Accion(models.TextChoices):
        CREAR = "CREAR", "Crear"
        EDITAR = "EDITAR", "Editar"
        VALIDAR = "VALIDAR", "Validar"
        CERRAR = "CERRAR", "Cerrar período"
        REABRIR = "REABRIR", "Reabrir período"

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


class ControlConcurrencia(models.Model):
    """
    Fila única usada como mutex transaccional para limitar operadores.
    La fila con pk=1 se crea mediante una señal post_migrate.
    """
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "asistencia_control_concurrencia"


class SesionEdicion(models.Model):
    """
    Representa una sesión de edición activa.
    El token evita que una sesión libere el bloqueo de otra.
    """
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sesiones_edicion_asistencia",
    )
    creada_en = models.DateTimeField(auto_now_add=True)
    heartbeat_en = models.DateTimeField(default=timezone.now)
    expira_en = models.DateTimeField()
    activa = models.BooleanField(default=True)

    class Meta:
        db_table = "asistencia_sesion_edicion"
        indexes = [
            models.Index(
                fields=["activa", "expira_en"],
                name="ix_sesion_act_expira",
            ),
        ]

    def __str__(self):
        return f"{self.usuario} — {self.token}"


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