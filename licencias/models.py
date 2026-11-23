from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError 
from django.core.validators import FileExtensionValidator
from django.db import models

from .clasificacion import CATEGORIA_CHOICES
from .dias import (
    ciclo_de,
    contar_dias_habiles,
    fecha_de_hoy,
    mes_inicio_ciclo,
    rango_en_anio,
    rango_en_ciclo,
)


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

    # RN-10: número del formulario en papel recepcionado. Es requisito previo
    # para emitir la disposición (RF-16); no para registrar la licencia.
    nro_formulario = models.CharField(
        max_length=20, null=True, blank=True,
        verbose_name="N° de formulario",
        help_text="Número del formulario en papel recepcionado (RN-10).",
    )


    # RN-08: resolución que autoriza a exceder el tope anual del artículo.
    # Si viene completa, la validación del tope deja pasar el exceso.
    resolucion_excepcion = models.CharField(
        max_length=100, null=True, blank=True,
        verbose_name="Resolución de excepción",
        help_text="N° y fecha de la resolución que autoriza exceder el tope anual (RN-08).",
    )

    # Fechas y observaciones
    desde = models.DateField()
    hasta = models.DateField(null=True, blank=True)
    observaciones = models.TextField(null=True, blank=True)

    # La licencia es del docente: se carga una vez y el sistema crea una
    # LicenciaOtorgada por cada materia o cargo afectado. Todas las de un
    # mismo pedido comparten el grupo (y la disposición).
    grupo = models.UUIDField(null=True, blank=True, db_index=True, editable=False)

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

        # M8: el artículo debe corresponder a la situación de revista de la
        # designación (un suplente no usa artículos de titular). Si la designación
        # no tiene situación cargada, no se valida.
        if self.designacion.situacion_revista:
            situacion_docente = self.designacion.get_situacion_revista_display()
            situacion_articulo = (self.articulo.sit_rev or '').strip()
            if situacion_articulo.lower() != situacion_docente.lower():
                raise ValidationError({
                    'articulo': (
                        f"El artículo {self.articulo.articulo} corresponde al "
                        f"personal {situacion_articulo.lower()} y esta designación "
                        f"es de personal {situacion_docente.lower()}."
                    )
                })

        # M8: una designación no puede tener dos licencias en el mismo día.
        # Una licencia abierta (sin "hasta") se toma como que sigue sin fin.
        fin = self.hasta or date.max
        superpuestas = LicenciaOtorgada.objects.filter(
            designacion_id=self.designacion_id,
            desde__lte=fin,
        ).filter(models.Q(hasta__isnull=True) | models.Q(hasta__gte=self.desde))
        if self.pk:
            superpuestas = superpuestas.exclude(pk=self.pk)
        otra = superpuestas.order_by('desde').first()
        if otra:
            hasta_otra = (
                otra.hasta.strftime('%d/%m/%Y') if otra.hasta else 'sin fecha de fin'
            )
            raise ValidationError({
                'desde': (
                    "Las fechas se superponen con otra licencia de este docente "
                    f"(artículo {otra.articulo.articulo}, del "
                    f"{otra.desde.strftime('%d/%m/%Y')} al {hasta_otra})."
                )
            })

        tope = self.articulo.tope_dias_anual
        if not tope:
            return

        # RN-08: con una resolución de excepción cargada, el tope no se aplica.
        # strip() para que un campo con solo espacios no cuente como resolución.
        if (self.resolucion_excepcion or '').strip():
            return

        # Import local: services importa models, así que no puede ir arriba.
        from .services import dias_usados_en_ciclo

        # RN-08: el tope es por ciclo lectivo (de marzo a febrero, según los
        # parámetros del sistema): una licencia que cruza de ciclo se reparte
        # y cada parte se controla contra el tope de su propio ciclo.
        hoy = fecha_de_hoy()
        fin_calculo = self.hasta or hoy  # licencia abierta: hasta hoy
        mes = mes_inicio_ciclo()
        ciclos = range(ciclo_de(self.desde, mes), ciclo_de(fin_calculo, mes) + 1)

        for ciclo in ciclos:
            rango = rango_en_ciclo(self.desde, self.hasta, ciclo, hoy, mes)
            if rango is None:
                continue
            inicio, fin = rango
            dias_pedidos = contar_dias_habiles(inicio, fin)

            # Al editar (self.pk existe) se excluye esta misma licencia del
            # conteo, para que no se cuente contra sí misma. En un alta es None.
            # Se cuenta por código del nomenclador: cada código tiene su tope.
            dias_ya_usados = dias_usados_en_ciclo(
                self.designacion.persona.dni,
                self.articulo,
                ciclo,
                excluir_id=self.pk,
                excluir_grupo=self.grupo,
            )

            if dias_ya_usados + dias_pedidos > tope:
                # La situación de revista sale del artículo del catálogo, que es
                # de donde viene el tope (titular, interino, suplente: arts. 3xx).
                situacion = (self.articulo.sit_rev or '').strip().lower()
                para = f" para el personal {situacion}" if situacion else ""
                en_ciclo = f" en el ciclo lectivo {ciclo}"
                raise ValidationError({
                    'hasta': (
                        f"Tope excedido. El límite del artículo {self.articulo.articulo} "
                        f"según el Estatuto Docente de la provincia del Chaco{para} "
                        f"es {tope} días por ciclo lectivo. "
                        f"El docente ya usó {dias_ya_usados} días{en_ciclo} y ahora "
                        f"solicita {dias_pedidos} más."
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

TAMANIO_MAXIMO_RESOLUCION = 5 * 1024 * 1024  # 5 MB


def validar_resolucion_pdf(archivo):
    """RF-16: hasta 5 MB y contenido que realmente empiece como un PDF."""
    if archivo.size > TAMANIO_MAXIMO_RESOLUCION:
        raise ValidationError("El archivo supera el máximo permitido de 5 MB.")
    archivo.seek(0)
    cabecera = archivo.read(5)
    archivo.seek(0)
    if cabecera != b'%PDF-':
        raise ValidationError("El archivo no es un PDF válido.")


class ResolucionAdjunta(models.Model):
    """RF-16: resolución ministerial o externa adjunta a una licencia (PDF)."""
    licencia = models.ForeignKey(
        LicenciaOtorgada, on_delete=models.CASCADE, related_name='resoluciones',
    )
    descripcion = models.CharField(
        max_length=200,
        help_text="Por ejemplo: Resolución ministerial N° 123/2026.",
    )
    archivo = models.FileField(
        upload_to='resoluciones/%Y/%m/',
        validators=[FileExtensionValidator(['pdf']), validar_resolucion_pdf],
    )
    subido_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-subido_en']

    def __str__(self):
        return self.descripcion


class RenglonMensual(models.Model):
    """
    Renglón de la planilla mensual (cuadros IL-01 / IL-02), generado desde la
    asistencia diaria por `licencias.planilla_mensual.procesar_mes`.

    - RF-12 / RN-10: hay un renglón por cada materia o cargo que el agente
      tenía en los días del bloque, sin excepciones.
    - RF-13: `horas` son las horas cátedra de esa designación en los días
      afectados, tomadas de su horario semanal.
    - RF-14: `desde` y `hasta` son el inicio y el fin del período continuo
      cargado en la diaria (iguales si fue una sola jornada).
    - RF-15: al elegir el `articulo` se completan `cod_licencia` y `planilla`.
    - RF-16 / RN-11: todas las materias del bloque comparten `disp_numero`.
    - RN-07 / RN-08: `oficina` y `anio_planilla` nacen precargados.
    - RF-20: guarda quién lo generó o modificó y cuándo.
    """

    PLANILLA_CHOICES = [('IL-01', 'IL-01'), ('IL-02', 'IL-02')]

    anio = models.PositiveSmallIntegerField()
    mes = models.PositiveSmallIntegerField()
    designacion = models.ForeignKey(
        'personal.Designacion', on_delete=models.PROTECT,
        related_name='renglones_mensuales',
    )
    # Marca de la diaria que originó el renglón: LIC, LT, P o I.
    marca = models.CharField(max_length=12)
    desde = models.DateField()
    hasta = models.DateField()
    dias = models.PositiveSmallIntegerField(default=0)
    horas = models.DecimalField(max_digits=7, decimal_places=2, default=0)

    articulo = models.ForeignKey(
        LicenciaArticulo, on_delete=models.RESTRICT, null=True, blank=True,
        related_name='renglones_mensuales',
    )
    cod_licencia = models.CharField(max_length=12, blank=True)
    planilla = models.CharField(max_length=10, blank=True, choices=PLANILLA_CHOICES)

    oficina = models.CharField(max_length=10, default='1452')
    anio_planilla = models.PositiveSmallIntegerField()

    disp_tipo = models.CharField(max_length=30, blank=True)
    disp_numero = models.CharField(max_length=20, blank=True)
    disp_anio = models.SmallIntegerField(null=True, blank=True)
    # Resolución del M.E.C.C.yT.: dato externo (RF-16).
    resolucion = models.CharField(max_length=100, blank=True)

    nro_formulario = models.CharField(max_length=30, blank=True)
    licencia = models.ForeignKey(
        LicenciaOtorgada, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='renglones_mensuales',
    )
    # La diaria cambió después de emitida la disposición: se conserva el
    # renglón y se avisa para corregirlo a mano (INC-02).
    desactualizado = models.BooleanField(default=False)

    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='renglones_mensuales_creados',
    )
    actualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='renglones_mensuales_actualizados',
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'licencia_renglon_mensual'
        verbose_name = 'Renglón de planilla mensual'
        verbose_name_plural = 'Renglones de planilla mensual'
        ordering = ['designacion__persona__apellido_nombre', 'desde', 'designacion_id']
        constraints = [
            models.UniqueConstraint(
                fields=['anio', 'mes', 'designacion', 'marca', 'desde', 'hasta'],
                name='uq_renglon_mensual_bloque',
            ),
        ]
        indexes = [
            models.Index(fields=['anio', 'mes'], name='ix_renglon_periodo'),
        ]

    def __str__(self):
        return (
            f"{self.anio}-{self.mes:02d} · designación {self.designacion_id} · "
            f"{self.marca} {self.desde:%d/%m} al {self.hasta:%d/%m}"
        )

    @property
    def clave_de_bloque(self):
        """Renglones del mismo agente y período: comparten la disposición (RN-11)."""
        return (self.designacion.persona_id, self.desde, self.hasta)

    def imputar(self, articulo):
        """
        RF-15: al elegir el artículo se autocompleta el código de licencia y
        el renglón se deriva al cuadro que corresponde.
        """
        from .planilla_mensual import planilla_del_renglon

        self.articulo = articulo
        self.cod_licencia = articulo.cod_licencia if articulo else ''
        self.planilla = planilla_del_renglon(self.marca, articulo)
