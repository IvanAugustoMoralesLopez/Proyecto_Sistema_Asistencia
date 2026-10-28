"""
Modelos de la app `licencias`, mapeados a planilla_personal.sql (v4).

El script SQL es la fuente de verdad del esquema (ENUM, CHECK, triggers,
procedimientos y vistas que Django no puede crear), por eso los modelos son
`managed = False`: Django lee y escribe esas tablas pero no las migra.
La auditoría (RF-20) la hacen los triggers sobre la tabla `auditoria`.
"""
from datetime import date

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from .clasificacion import PLANILLA_CHOICES
from .dias import contar_dias_habiles


class LicenciaArticulo(models.Model):
    CLASE_CHOICES = [
        ('SALUD', 'Salud'),
        ('ADMINISTRATIVA', 'Administrativa'),
    ]
    TOPE_UNIDAD_CHOICES = [('DIAS', 'Días'), ('ANIOS', 'Años')]
    TOPE_PERIODO_CHOICES = [
        ('POR_VEZ', 'Por vez'),
        ('POR_ANIO', 'Por año'),
        ('POR_DECENIO', 'Por decenio'),
    ]

    cod_licencia = models.CharField(max_length=12)
    articulo = models.CharField(max_length=20, null=True, blank=True)
    clase = models.CharField(max_length=15, choices=CLASE_CHOICES)
    tipo_licencia = models.CharField(max_length=120, null=True, blank=True)
    categoria_informe = models.CharField(max_length=5, choices=PLANILLA_CHOICES)  # RN-04 / RN-05
    es_largo_tratamiento = models.BooleanField(default=False)  # marca LT en la asistencia
    sit_rev = models.CharField(max_length=20, null=True, blank=True)
    goce_haberes = models.CharField(max_length=30, null=True, blank=True)
    autoridad = models.CharField(max_length=30, null=True, blank=True)
    plazo = models.CharField(max_length=200, null=True, blank=True)

    # Topes (RF-18, RN-08)
    tope_cantidad = models.PositiveIntegerField(null=True, blank=True)
    tope_unidad = models.CharField(max_length=5, choices=TOPE_UNIDAD_CHOICES, null=True, blank=True)
    tope_periodo = models.CharField(max_length=11, choices=TOPE_PERIODO_CHOICES, null=True, blank=True)
    tope_dias_corridos = models.BooleanField(null=True, blank=True)
    antiguedad_min_meses = models.PositiveSmallIntegerField(null=True, blank=True)
    tope_cantidad_sin_antig = models.PositiveIntegerField(null=True, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'licencia_articulo'
        verbose_name = 'Artículo de Licencia'
        verbose_name_plural = 'Artículos de Licencia'

    def __str__(self):
        return f"{self.articulo} - {self.tipo_licencia}"

    @property
    def tope_dias_anual(self):
        """Tope en días por año (RN-08), o None si el artículo no tiene uno de ese tipo."""
        if self.tope_unidad == 'DIAS' and self.tope_periodo == 'POR_ANIO':
            return self.tope_cantidad
        return None


class Disposicion(models.Model):
    """Disposición interna (numeración correlativa) o resolución externa (RF-16)."""
    TIPO_CHOICES = [('INTERNA', 'Interna'), ('EXTERNA', 'Externa')]

    tipo = models.CharField(max_length=8, choices=TIPO_CHOICES)
    dni_beneficiario = models.CharField(max_length=10, null=True, blank=True)
    oficina_codigo = models.CharField(max_length=10)
    anio = models.SmallIntegerField()
    numero = models.PositiveIntegerField()
    org_emisor = models.CharField(max_length=60, null=True, blank=True)
    fecha_emision = models.DateField(null=True, blank=True)
    periodo_mes = models.PositiveSmallIntegerField(null=True, blank=True)
    anulada = models.BooleanField(default=False)
    observaciones = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'disposicion'
        unique_together = ('tipo', 'oficina_codigo', 'anio', 'numero')
        verbose_name = 'Disposición'
        verbose_name_plural = 'Disposiciones'

    def __str__(self):
        return f"{self.get_tipo_display()} {self.numero}/{self.anio} ({self.oficina_codigo})"


class LicenciaOtorgada(models.Model):
    designacion = models.ForeignKey('personal.Designacion', on_delete=models.RESTRICT)
    articulo = models.ForeignKey(LicenciaArticulo, on_delete=models.RESTRICT)
    # Foto de la situación de revista al momento de la licencia (sin FK en la BD).
    sit_rev = models.CharField(max_length=20, null=True, blank=True)

    disposicion_interna = models.ForeignKey(
        Disposicion, null=True, blank=True, on_delete=models.RESTRICT,
        related_name='licencias_internas',
    )
    resolucion_externa = models.ForeignKey(
        Disposicion, null=True, blank=True, on_delete=models.RESTRICT,
        related_name='licencias_externas',
    )
    nro_formulario_papel = models.CharField(max_length=20, null=True, blank=True)  # RN-10
    fecha_recepcion_formulario = models.DateField(null=True, blank=True)
    sello_regional_as = models.CharField(max_length=30, null=True, blank=True)
    justifica = models.BooleanField(default=False)

    desde = models.DateField()
    hasta = models.DateField(null=True, blank=True)
    anulada = models.BooleanField(default=False)
    observaciones = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'licencia_otorgada'
        verbose_name = 'Licencia Otorgada'
        verbose_name_plural = 'Licencias Otorgadas'

    def __str__(self):
        return f"Licencia {self.articulo} para designación {self.designacion_id}"

    def clean(self):
        super().clean()

        # Chequeamos los *_id (no la relación) para evitar RelatedObjectDoesNotExist
        # cuando el formulario todavía no tiene designación o artículo.
        if not (self.designacion_id and self.desde):
            return

        if self.hasta and self.hasta < self.desde:
            raise ValidationError({'hasta': 'La fecha "hasta" no puede ser anterior a "desde".'})

        # RN-10 (espejo del CHECK ck_lic_papel): para vincular la disposición
        # interna hace falta el número de formulario en papel.
        if self.disposicion_interna_id and not self.nro_formulario_papel:
            raise ValidationError({
                'nro_formulario_papel':
                    'RN-10: se necesita el número de formulario en papel para vincular la disposición.'
            })

        if self.anulada:
            return

        self._validar_superposicion()
        self._validar_tope_anual()

    def _validar_superposicion(self):
        """Espejo de sp_validar_licencia: sin licencias superpuestas en la misma designación."""
        otras = LicenciaOtorgada.objects.filter(
            designacion_id=self.designacion_id, anulada=False,
        ).exclude(pk=self.pk)
        if self.hasta:
            otras = otras.filter(desde__lte=self.hasta)
        otras = otras.filter(Q(hasta__isnull=True) | Q(hasta__gte=self.desde))
        if otras.exists():
            raise ValidationError(
                'La designación ya tiene una licencia que se superpone con ese período.'
            )

    def _validar_tope_anual(self):
        """RN-08 (tope anual en días). Hoy valida solo altas; ver paso 3."""
        if self.pk or not self.articulo_id:
            return
        tope = self.articulo.tope_dias_anual
        if not tope:
            return

        # Import local: services importa models, así que no puede ir arriba.
        from .services import dias_usados_en_anio

        dias_ya_usados = dias_usados_en_anio(
            self.designacion.persona.dni,
            self.articulo.articulo,
            self.desde.year,
        )

        # Licencia abierta: se calcula hasta hoy (igual criterio que services.py).
        fin_calculo = self.hasta or date.today()
        dias_pedidos = contar_dias_habiles(self.desde, fin_calculo)

        if dias_ya_usados + dias_pedidos > tope:
            raise ValidationError({
                'hasta': (
                    f"Tope excedido (RN-08). El límite del artículo es {tope} días. "
                    f"El docente ya usó {dias_ya_usados} días y ahora solicita "
                    f"{dias_pedidos} más."
                )
            })
