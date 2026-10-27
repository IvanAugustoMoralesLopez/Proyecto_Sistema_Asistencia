from django.db import models

class LicenciaArticulo(models.Model):
    CLASE_CHOICES = [
        ('Licencia', 'Licencia'),
        ('Permiso', 'Permiso'),
        ('Inasistencia', 'Inasistencia'),
    ]
    CATEGORIA_CHOICES = [
        ('Enfermedad común', 'Enfermedad común'),
        ('Largo tratamiento', 'Largo tratamiento'),
        ('Otros', 'Otros'),
    ]
    SIT_REV_CHOICES = [
        ('Titular', 'Titular'),
        ('Interino', 'Interino'),
        ('Suplente', 'Suplente'),
    ]

    cod_licencia = models.CharField(max_length=12, unique=True)
    articulo = models.CharField(max_length=20)
    clase = models.CharField(max_length=15, choices=CLASE_CHOICES, default='Licencia')
    tipo_licencia = models.CharField(max_length=120)
    categoria_informe = models.CharField(max_length=20, choices=CATEGORIA_CHOICES, default='Otros')
    sit_rev = models.CharField(max_length=20, choices=SIT_REV_CHOICES)
    goce_haberes = models.CharField(max_length=30)
    autoridad = models.CharField(max_length=30)
    plazo = models.CharField(max_length=200)
    
    tope_dias_anual = models.PositiveSmallIntegerField(
        null=True, blank=True,
        verbose_name="Tope de días por año",
        help_text="Vacío = sin tope numérico.",
    )

    class Meta:
        db_table = 'licencia_articulo'
        unique_together = ('id', 'sit_rev')
        verbose_name = 'Artículo de Licencia'
        verbose_name_plural = 'Artículos de Licencia'

    def __str__(self):
        return f"{self.articulo} - {self.tipo_licencia}"


class LicenciaOtorgada(models.Model):
    designacion = models.ForeignKey('personal.Designacion', on_delete=models.RESTRICT)
    articulo = models.ForeignKey(LicenciaArticulo, on_delete=models.RESTRICT)
    sit_rev = models.CharField(max_length=20)
    
    # Datos de la disposición (DL-01)
    disp_tipo = models.CharField(max_length=20, null=True, blank=True)
    disp_oficina = models.CharField(max_length=10, null=True, blank=True)
    disp_numero = models.CharField(max_length=20, null=True, blank=True)
    disp_anio = models.SmallIntegerField(null=True, blank=True)
    sello_regional_as = models.CharField(max_length=30, null=True, blank=True)
    justifica = models.BooleanField(null=True, blank=True)
    
    # Fechas y observaciones
    desde = models.DateField()
    hasta = models.DateField(null=True, blank=True)
    observaciones = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'licencia_otorgada'
        verbose_name = 'Licencia Otorgada'
        verbose_name_plural = 'Licencias Otorgadas'

    def __str__(self):
        return f"Licencia {self.articulo} para designación {self.designacion_id}"