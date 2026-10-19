from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from personal.models import Designacion
from licencias.models import LicenciaOtorgada

from .models import (
    RegistroAsistencia,
    MarcaAsistencia,
)


class RegistroAsistenciaForm(forms.ModelForm):
    class Meta:
        model = RegistroAsistencia
        fields = [
            "designacion",
            "fecha",
            "marca",
            "horas_inasistidas",
            "licencia",
            "observaciones",
        ]
        widgets = {
            "fecha": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
            "horas_inasistidas": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "0",
                    "step": "0.25",
                }
            ),
            "observaciones": forms.Textarea(
                attrs={"class": "form-control", "rows": 3}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["designacion"].queryset = (
            Designacion.objects.filter(
                activo=True,
                persona__activa=True,
            ).select_related(
                "persona",
                "cargo",
                "espacio_curricular",
            )
        )

        self.fields["marca"].queryset = MarcaAsistencia.objects.filter(
            activa=True,
        )

        self.fields["licencia"].queryset = (
            LicenciaOtorgada.objects.filter(
                estado=LicenciaOtorgada.Estado.APROBADA,
            ).select_related(
                "designacion__persona",
            )
        )

        self.fields["licencia"].required = False

        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean_fecha(self):
        fecha = self.cleaned_data["fecha"]

        if fecha.year < 2000:
            raise ValidationError(
                "La fecha debe ser igual o posterior al año 2000."
            )

        if fecha > timezone.localdate():
            raise ValidationError(
                "No se permite registrar asistencia de una fecha futura."
            )

        return fecha

    def clean(self):
        cleaned = super().clean()

        designacion = cleaned.get("designacion")
        marca = cleaned.get("marca")
        fecha = cleaned.get("fecha")
        licencia = cleaned.get("licencia")
        observaciones = cleaned.get("observaciones", "")

        if (
            marca
            and marca.requiere_observacion
            and not observaciones.strip()
        ):
            self.add_error(
                "observaciones",
                "Esta marca requiere una observación.",
            )

        if licencia and designacion:
            if licencia.designacion_id != designacion.pk:
                self.add_error(
                    "licencia",
                    "La licencia no corresponde a la designación elegida.",
                )

            if fecha and not licencia.desde <= fecha <= licencia.hasta:
                self.add_error(
                    "licencia",
                    "La fecha no está dentro del período de licencia.",
                )

        return cleaned


class FiltroAsistenciaForm(forms.Form):
    dni = forms.CharField(
        required=False,
        max_length=12,
        label="DNI",
    )
    apellido_nombre = forms.CharField(
        required=False,
        max_length=120,
        label="Apellido y nombre",
    )
    desde = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    hasta = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    marca = forms.ModelChoiceField(
        required=False,
        queryset=MarcaAsistencia.objects.filter(activa=True),
        empty_label="Todas las marcas",
    )

    def clean(self):
        cleaned = super().clean()
        desde = cleaned.get("desde")
        hasta = cleaned.get("hasta")

        if desde and hasta and hasta < desde:
            self.add_error(
                "hasta",
                "La fecha final debe ser igual o posterior a la inicial.",
            )

        return cleaned


class CierreMensualForm(forms.Form):
    anio = forms.IntegerField(min_value=2000, max_value=2100)
    mes = forms.IntegerField(min_value=1, max_value=12)


class ReaperturaMensualForm(forms.Form):
    motivo = forms.CharField(
        max_length=500,
        min_length=10,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "class": "form-control",
                "placeholder": "Explique por qué se debe reabrir el período.",
            }
        ),
        help_text="El motivo debe tener al menos 10 caracteres.",
    )