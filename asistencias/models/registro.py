from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from .marcas import MarcaAsistencia


def licencia_cubre_fecha(licencia, fecha):
    """
    Indica si la fecha está dentro del período de la licencia.
    Una licencia sin fecha "hasta" se considera abierta.
    """
    if fecha < licencia.desde:
        return False

    return licencia.hasta is None or fecha <= licencia.hasta


class RegistroAsistencia(models.Model):
    class Estado(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador"
        VALIDADO = "VALIDADO", "Validado"

    class EstadoJustificacion(models.TextChoices):
        NO_APLICA = "NO_APLICA", "No aplica"
        INJUSTIFICADA = "INJUSTIFICADA", "Injustificada"
        EN_TRAMITE = "EN_TRAMITE", "En trámite"
        JUSTIFICADA = "JUSTIFICADA", "Justificada"

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

    # Flujo de la inasistencia al recibir el formulario en papel (RF-09).
    estado_justificacion = models.CharField(
        max_length=14,
        choices=EstadoJustificacion.choices,
        default=EstadoJustificacion.NO_APLICA,
    )
    nro_formulario = models.CharField(max_length=30, blank=True)
    fecha_recepcion = models.DateField(null=True, blank=True)
    recepcionado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="formularios_recepcionados",
    )

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
        permissions = [
            ("validar_registro", "Puede validar registros de asistencia"),
            (
                "recepcionar_formulario",
                "Puede recepcionar formularios en papel",
            ),
            (
                "modificar_jornada_cerrada",
                "Puede modificar registros de una jornada cerrada",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["designacion", "fecha"],
                name="uq_asist_designacion_fecha",
            ),
            models.CheckConstraint(
                condition=Q(horas_inasistidas__gte=0),
                name="ck_asist_horas_no_negativas",
            ),
            # En trámite o justificada requiere el nº de formulario físico.
            models.CheckConstraint(
                condition=(
                    Q(estado_justificacion__in=["NO_APLICA", "INJUSTIFICADA"])
                    | ~Q(nro_formulario="")
                ),
                name="ck_asist_formulario_requerido",
            ),
        ]
        indexes = [
            models.Index(
                fields=["fecha", "marca"],
                name="ix_asist_fecha_marca",
            ),
            models.Index(
                fields=["estado_justificacion", "fecha"],
                name="ix_asist_justif_fecha",
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
            raise ValidationError({
                "licencia": (
                    "La licencia no pertenece a la designación seleccionada."
                )
            })

        if (
            self.licencia_id
            and self.fecha
            and not licencia_cubre_fecha(self.licencia, self.fecha)
        ):
            raise ValidationError({
                "licencia": "La fecha no está comprendida en la licencia."
            })

    def __str__(self):
        return f"{self.designacion_id} — {self.fecha}"
