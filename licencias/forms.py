
from django.db.models import Q
from django import forms
from personal.models import Designacion, TipoInstrumentoLegal
from .models import LicenciaArticulo, LicenciaOtorgada, ResolucionAdjunta
from .services import articulos_para_asistente
from django.utils.dateparse import parse_date


class LicenciaArticuloForm(forms.ModelForm):
    class Meta:
        model = LicenciaArticulo
        fields = [
            "cod_licencia",
            "articulo",
            "tipo_licencia",
            "clase",
            "categoria_informe",
            "sit_rev",
            "goce_haberes",
            "autoridad",
            "plazo",
            "tope_dias_anual",
        ]

        widgets = {
            "cod_licencia": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ej.: LIC-001",
            }),
            "articulo": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ej.: Art. 12",
            }),
            "tipo_licencia": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Descripción del tipo de licencia",
            }),
            "clase": forms.Select(attrs={"class": "form-select"}),
            "categoria_informe": forms.Select(attrs={"class": "form-select"}),
            "sit_rev": forms.Select(attrs={"class": "form-select"}),
            "goce_haberes": forms.TextInput(attrs={"class": "form-control"}),
            "autoridad": forms.TextInput(attrs={"class": "form-control"}),
            "plazo": forms.TextInput(attrs={"class": "form-control"}),
            "tope_dias_anual": forms.NumberInput(attrs={
                "class": "form-control",
                "min": 1,
                "placeholder": "Dejar vacío si no tiene tope numérico",
            }),
        }

        labels = {
            "cod_licencia": "Código de licencia",
            "articulo": "Artículo",
            "tipo_licencia": "Tipo de licencia",
            "clase": "Clase",
            "categoria_informe": "Categoría del informe",
            "sit_rev": "Situación de revista",
            "goce_haberes": "Goce de haberes",
            "autoridad": "Autoridad competente",
            "plazo": "Plazo o condición",
            "tope_dias_anual": "Tope de días por año",
        }

class SelectDesignacion(forms.Select):
    """RF-15: cada opción lleva la situación de revista de su designación."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        opcion = super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs,
        )
        designacion = getattr(value, "instance", None)
        if designacion is not None and designacion.situacion_revista:
            opcion["attrs"]["data-situacion"] = (
                designacion.get_situacion_revista_display().lower()
            )
        return opcion

def _etiqueta_designacion(designacion):
    """Texto de cada opción del desplegable: la designación, su situación de
    revista y su materia (para distinguir designaciones del mismo docente)."""
    etiqueta = str(designacion)
    if designacion.situacion_revista:
        etiqueta += f" - {designacion.get_situacion_revista_display()}"
    if designacion.espacio_curricular_id:
        etiqueta += f" - {designacion.espacio_curricular.nombre}"
    if designacion.carrera_id:
        etiqueta += f" ({designacion.carrera.nombre})"
    return etiqueta

class LicenciaOtorgadaForm(forms.ModelForm):
    justifica = forms.TypedChoiceField(
        choices=[
            ("", "Sin especificar"),
            ("True", "Sí"),
            ("False", "No"),
        ],
        coerce=lambda value: None if value == "" else value == "True",
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        fecha_desde = None

        if self.is_bound:
            fecha_desde = parse_date(self.data.get("desde", ""))
        elif self.instance and self.instance.pk:
            fecha_desde = self.instance.desde

        designaciones = Designacion.objects.filter(activo=True)

        if fecha_desde:
            designaciones = designaciones.filter(
                desde__lte=fecha_desde
            ).filter(
                Q(hasta__isnull=True) | Q(hasta__gte=fecha_desde)
            )

        # N2: al editar, siempre se ofrece la designación que la licencia ya
        # tiene, aunque haya sido dada de baja; si no, la licencia no se puede
        # guardar. En un alta no hay designación previa y no se agrega nada.
        if self.instance.designacion_id:
            designaciones = designaciones | Designacion.objects.filter(
                pk=self.instance.designacion_id
            )

        self.fields["designacion"].queryset = (
            designaciones.select_related(
                "persona", "cargo", "espacio_curricular", "carrera"
            ).order_by("persona__apellido_nombre")
        )
        # La opción muestra también la situación de revista de la designación.
        self.fields["designacion"].label_from_instance = _etiqueta_designacion

        # RF-05: el tipo de instrumento sale del catálogo de instrumentos legales.
        self.fields["disp_tipo"] = forms.ChoiceField(
            label="Tipo de instrumento",
            required=False,
            choices=TipoInstrumentoLegal.opciones(
                actual=self.instance.disp_tipo or ""
            ),
            widget=forms.Select(attrs={"class": "form-select"}),
        )

        # RN-07 / RN-08: en un alta, Oficina y Año nacen precargados.
        if not self.instance.pk:
            from reportes.models import ParametroSistema
            from .dias import fecha_de_hoy

            self.fields["disp_oficina"].initial = (
                ParametroSistema.obtener().codigo_oficina
            )
            self.fields["disp_anio"].initial = (
                fecha_desde.year if fecha_desde else fecha_de_hoy().year
            )

    def datos_articulos(self):
        """RF-15: catálogo con su planilla de salida, para el asistente."""
        return articulos_para_asistente()

    class Meta:
        model = LicenciaOtorgada
        fields = [ 
            "designacion",
            "articulo",
            "sit_rev",
            "desde",
            "hasta",
            "disp_tipo",
            "disp_oficina",
            "disp_numero",
            "disp_anio",
            "sello_regional_as",
            "justifica",
            "nro_formulario",
            "resolucion_excepcion",
            "observaciones",
        ]

        widgets = {
            "designacion": SelectDesignacion(attrs={"class": "form-select"}),
            "articulo": forms.Select(attrs={"class": "form-select"}),
            "sit_rev": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Situación de revista",
            }),
            "desde": forms.DateInput(format="%Y-%m-%d", attrs={
                "class": "form-control",
                "type": "date",
            }),
            "hasta": forms.DateInput(format="%Y-%m-%d", attrs={
                "class": "form-control",
                "type": "date",
            }),
            "disp_tipo": forms.TextInput(attrs={"class": "form-control"}),
            "disp_oficina": forms.TextInput(attrs={"class": "form-control"}),
            "disp_numero": forms.TextInput(attrs={"class": "form-control"}),
            "disp_anio": forms.NumberInput(attrs={
                "class": "form-control",
                "min": 1900,
                "max": 2100,
            }),
            "sello_regional_as": forms.TextInput(attrs={"class": "form-control"}),
            "nro_formulario": forms.TextInput(attrs={"class": "form-control"}),
            "resolucion_excepcion": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "N° y fecha de la resolución",
            }),
            "observaciones": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
            }),
        }


        labels = {
            "designacion": "Designación",
            "articulo": "Artículo de licencia",
            "sit_rev": "Situación de revista",
            "desde": "Desde",
            "hasta": "Hasta",
            "disp_tipo": "Tipo de disposición",
            "disp_oficina": "Oficina emisora",
            "disp_numero": "Número de disposición",
            "disp_anio": "Año de disposición",
            "sello_regional_as": "Sello regional",
            "justifica": "¿Está justificada?",
            "nro_formulario": "N° de formulario",
            "resolucion_excepcion": "Resolución de excepción",
            "observaciones": "Observaciones",
        }


class FiltroLicenciasForm(forms.Form):
    """
    Filtros del listado de licencias (GET). Valida los parámetros de la URL
    para que un valor inválido (ej. ?articulo=abc) no rompa la página.
    """

    docente = forms.CharField(required=False)
    articulo = forms.ModelChoiceField(
        queryset=LicenciaArticulo.objects.all(), required=False,
    )
    fecha_desde = forms.DateField(required=False)
    fecha_hasta = forms.DateField(required=False) 

class ResolucionAdjuntaForm(forms.ModelForm):
    """RF-16: formulario para adjuntar una resolución (PDF) a una licencia."""

    class Meta:
        model = ResolucionAdjunta
        fields = ["descripcion", "archivo"]
        widgets = {
            "descripcion": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ej.: Resolución ministerial N° 123/2026",
            }),
            "archivo": forms.ClearableFileInput(attrs={
                "class": "form-control",
                "accept": "application/pdf",
            }),
        }
        labels = {
            "descripcion": "Descripción",
            "archivo": "Archivo PDF (máximo 5 MB)",
        }


class LicenciaDocenteForm(forms.Form):
    """
    Licencia por docente: se elige el docente, el artículo y el período; el
    sistema propone sus materias afectadas (designaciones) y el número de
    disposición, que se puede cambiar.
    """

    persona = forms.ModelChoiceField(
        label="Docente",
        queryset=None,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    articulo = forms.ModelChoiceField(
        label="Artículo",
        queryset=LicenciaArticulo.objects.all().order_by("articulo"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    desde = forms.DateField(
        label="Desde",
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"class": "form-control", "type": "date"}),
    )
    hasta = forms.DateField(
        label="Hasta",
        required=False,
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"class": "form-control", "type": "date"}),
        help_text="Vacío si es una licencia abierta (por ejemplo, largo tratamiento).",
    )
    nro_formulario = forms.CharField(
        label="N° de formulario (opcional)",
        required=False,
        max_length=20,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "F-2026-____"}),
    )
    justifica = forms.TypedChoiceField(
        label="¿Está justificada?",
        choices=[("", "Sin especificar"), ("True", "Sí"), ("False", "No")],
        coerce=lambda value: None if value == "" else value == "True",
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    resolucion_excepcion = forms.CharField(
        label="Resolución de excepción",
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "N° y fecha (solo si supera el tope anual)"}),
    )
    observaciones = forms.CharField(
        label="Observaciones",
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}),
    )
    designaciones = forms.MultipleChoiceField(
        label="Materias y cargos afectados",
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    disp_tipo = forms.ChoiceField(
        label="Tipo",
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    disp_oficina = forms.CharField(
        label="Oficina",
        required=False,
        max_length=10,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    disp_numero = forms.CharField(
        label="Número",
        required=False,
        max_length=20,
        widget=forms.TextInput(attrs={"class": "form-control", "inputmode": "numeric"}),
    )
    disp_anio = forms.IntegerField(
        label="Año",
        required=False,
        min_value=2000,
        max_value=2100,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )

    def __init__(self, *args, materias=None, **kwargs):
        super().__init__(*args, **kwargs)
        from personal.models import Persona

        self.fields["persona"].queryset = (
            Persona.objects.filter(designaciones__activo=True)
            .distinct()
            .order_by("apellido_nombre")
        )
        self.fields["persona"].label_from_instance = (
            lambda persona: f"{persona.apellido_nombre} · DNI {persona.dni}"
        )
        self.fields["articulo"].label_from_instance = (
            lambda articulo: f"{articulo.articulo} - {articulo.tipo_licencia}"
            + (f" ({articulo.sit_rev})" if articulo.sit_rev else "")
        )
        self.fields["disp_tipo"].choices = TipoInstrumentoLegal.opciones(
            actual=(self.data.get("disp_tipo") if self.is_bound else "") or ""
        )
        self.fields["designaciones"].choices = [
            (str(m["designacion"].pk), m.get("etiqueta", m["materia"]))
            for m in (materias or [])
        ]

    def clean_disp_numero(self):
        numero = (self.cleaned_data.get("disp_numero") or "").strip()
        if numero and not numero.isdigit():
            raise forms.ValidationError("El número de disposición es solo números.")
        return numero

    def clean(self):
        cleaned = super().clean()
        desde, hasta = cleaned.get("desde"), cleaned.get("hasta")
        if desde and hasta and hasta < desde:
            self.add_error("hasta", "La fecha Hasta no puede ser anterior a la fecha Desde.")
        if cleaned.get("disp_numero") and not cleaned.get("disp_anio"):
            self.add_error("disp_anio", "Indicá el año de la disposición.")
        return cleaned
