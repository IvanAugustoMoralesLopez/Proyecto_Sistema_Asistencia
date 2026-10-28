from django.db import models 
from django.core.exceptions import ValidationError
from datetime import date, timedelta 


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

    def clean(self):
        super().clean()

        # Importación local para evitar el error circular
        from .services import dias_usados_en_anio
        from asistencias.models import DiaNoLaborable

        # Agregamos hasattr para evitar el RelatedObjectDoesNotExist si la designación aún no cargó
        if hasattr(self, 'designacion') and self.articulo and self.articulo.tope_dias_anual and self.desde:
            anio_actual = self.desde.year

            # 1. Calculamos días históricos consumidos (excluyendo la licencia actual si se está editando)
            dias_ya_usados = dias_usados_en_anio(
                self.designacion.persona.dni,
                self.articulo.articulo,
                anio_actual
            )
            
            # Si estamos editando una licencia existente, restamos sus días previos para no contar doble
            # (Asume que en el form se validarán las ediciones, o se usa self.pk para control)
            
            if not self.pk: # Solo validamos la suma en licencias nuevas
                # 2. Calculamos los días hábiles de la solicitud actual
                fin_calculo = self.hasta if self.hasta else date.today()
                
                feriados = set(DiaNoLaborable.objects.filter(
                    fecha__range=[self.desde, fin_calculo]
                ).values_list('fecha', flat=True))

                dias_pedidos = 0
                rango = (fin_calculo - self.desde).days + 1
                
                for i in range(rango):
                    dia_evaluado = self.desde + timedelta(days=i)
                    if dia_evaluado.weekday() < 5 and dia_evaluado not in feriados:
                        dias_pedidos += 1

                # 3. Verificamos que la suma no supere el tope anual
                if (dias_ya_usados + dias_pedidos) > self.articulo.tope_dias_anual:
                    raise ValidationError({
                        'hasta': f"Tope excedido (RN-08). El límite del artículo es {self.articulo.tope_dias_anual} días. El docente ya usó {dias_ya_usados} días y ahora solicita {dias_pedidos} más."
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