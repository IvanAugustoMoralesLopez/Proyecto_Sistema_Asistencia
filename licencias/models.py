from datetime import date

from django.core.exceptions import ValidationError
from django.db import models

from .clasificacion import CATEGORIA_CHOICES
from .dias import contar_dias_habiles


class LicenciaArticulo(models.Model):
    CLASE_CHOICES = [
        ('Licencia', 'Licencia'),
        ('Permiso', 'Permiso'),
        ('Inasistencia', 'Inasistencia'),
    ]
    # Se mantiene el nombre de clase por compatibilidad; los valores salen de
    # clasificacion.py (RN-04 / RN-05).
    CATEGORIA_CHOICES = CATEGORIA_CHOICES
    SIT_REV_CHOICES = [
        ('Titular', 'Titular'),
        ('Interino', 'Interino'),
        ('Suplente', 'Suplente'),
    ]

    cod_licencia = models.CharField(max_length=12, unique=True)
    articulo = models.CharField(max_length=20)
    clase = models.CharField(max_length=15, choices=CLASE_CHOICES, default='Licencia')
    tipo_licencia = models.CharField(max_length=120)
    # Sin default a propósito: cada artículo debe clasificarse explícitamente
    # en IL-01 o IL-02 (imputación estricta).
    categoria_informe = models.CharField(max_length=30, choices=CATEGORIA_CHOICES)
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

    def clean(self):
        super().clean()

        # Chequeamos los *_id (no la relación) para evitar RelatedObjectDoesNotExist
        # cuando el formulario del Admin todavía no tiene designación o artículo.
        if not (self.articulo_id and self.designacion_id and self.desde):
            return

        # Hasta no puede ser anterior a Desde. Se valida acá, antes del tope, para
        # que un rango invertido no genere además un error de tope engañoso.
        if self.hasta and self.hasta < self.desde:
            raise ValidationError({
                'hasta': 'La fecha Hasta no puede ser anterior a la fecha Desde.'
            })

        tope = self.articulo.tope_dias_anual
        if not tope:
            return

        # TODO (RN-08): faltan el cruce de año y la excepción por resolución.

        # Import local: services importa models, así que no puede ir arriba.
        from .services import dias_usados_en_anio

        # Al editar (self.pk existe) se excluye esta misma licencia del conteo,
        # para que no se cuente contra sí misma. En un alta, self.pk es None.
        dias_ya_usados = dias_usados_en_anio(
            self.designacion.persona.dni,
            self.articulo.articulo,
            self.desde.year,
            excluir_id=self.pk,
        )

        # Licencia abierta: se calcula hasta hoy (igual criterio que services.py).
        fin_calculo = self.hasta or date.today()
        dias_pedidos = contar_dias_habiles(self.desde, fin_calculo)

        if dias_ya_usados + dias_pedidos > tope:
            raise ValidationError({
                'hasta': (
                    f"Se superó el límite anual de este artículo: {tope} días. "
                    f"El docente ya usó {dias_ya_usados} días y ahora solicita "
                    f"{dias_pedidos} más."
                )
            })


class RegistroBitacora(models.Model):
    accion = models.CharField(max_length=50)
    descripcion = models.TextField()
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'registro_bitacora'
        verbose_name = 'Registro de Bitácora'
        verbose_name_plural = 'Registros de Bitácora'

    def __str__(self):
        return f"{self.fecha.strftime('%d/%m/%Y %H:%M')} - {self.accion}"
