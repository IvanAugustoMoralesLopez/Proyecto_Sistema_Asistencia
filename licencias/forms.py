
from django.db.models import Q
from django import forms
from personal.models import Designacion
from .models import LicenciaArticulo, LicenciaOtorgada
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

        self.fields["designacion"].queryset = (
            designaciones.select_related(
                "persona", "cargo"
            ).order_by("persona__apellido_nombre")
        )


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
            "observaciones",
        ]

        widgets = {
            "designacion": forms.Select(attrs={"class": "form-select"}),
            "articulo": forms.Select(attrs={"class": "form-select"}),
            "sit_rev": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Situación de revista",
            }),
            "desde": forms.DateInput(attrs={
                "class": "form-control",
                "type": "date",
            }),
            "hasta": forms.DateInput(attrs={
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
