from django import forms
from django.db import transaction

from .models import (
    Cargo,
    Designacion,
    EspacioCurricular,
    Horario,
    Persona,
    UnidadEducativa,
)


class BuscarLegajoForm(forms.Form):
    dni = forms.CharField(
        required=False,
        label="DNI",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Buscar por DNI",
            }
        ),
    )
    cargo = forms.ModelChoiceField(
        queryset=Cargo.objects.filter(activo=True).order_by("descripcion"),
        required=False,
        empty_label="Todos los cargos",
        label="Cargo",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    espacio_curricular = forms.ModelChoiceField(
        queryset=EspacioCurricular.objects.filter(activo=True)
        .select_related("carrera")
        .order_by("carrera__nombre", "nombre"),
        required=False,
        empty_label="Todos los espacios",
        label="Espacio curricular",
        widget=forms.Select(attrs={"class": "form-select"}),
    )


class PersonaForm(forms.ModelForm):
    class Meta:
        model = Persona
        fields = [
            "dni",
            "apellido_nombre",
            "sexo",
            "fecha_nacimiento",
            "estado_civil",
            "nacionalidad",
            "nro_dgi",
            "nro_dgr",
            "domicilio_calle",
            "barrio",
            "localidad",
            "codigo_postal",
            "provincia",
            "telefono",
            "email",
            "activa",
        ]
        widgets = {
            "dni": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "inputmode": "numeric",
                    "maxlength": "10",
                }
            ),
            "apellido_nombre": forms.TextInput(attrs={"class": "form-control"}),
            "sexo": forms.Select(attrs={"class": "form-select"}),
            "fecha_nacimiento": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "estado_civil": forms.TextInput(attrs={"class": "form-control"}),
            "nacionalidad": forms.TextInput(attrs={"class": "form-control"}),
            "nro_dgi": forms.TextInput(attrs={"class": "form-control"}),
            "nro_dgr": forms.TextInput(attrs={"class": "form-control"}),
            "domicilio_calle": forms.TextInput(attrs={"class": "form-control"}),
            "barrio": forms.TextInput(attrs={"class": "form-control"}),
            "localidad": forms.TextInput(attrs={"class": "form-control"}),
            "codigo_postal": forms.TextInput(attrs={"class": "form-control"}),
            "provincia": forms.TextInput(attrs={"class": "form-control"}),
            "telefono": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "activa": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["dni"].disabled = True
            self.fields["dni"].help_text = "El DNI identifica el legajo y no se modifica."

    def clean(self):
        cleaned_data = super().clean()
        nombre_completo = cleaned_data.get("apellido_nombre", "").strip()
        if not nombre_completo:
            self.add_error(
                "apellido_nombre",
                "Ingrese el apellido y nombre del agente.",
            )
        return cleaned_data


class DesignacionForm(forms.ModelForm):
    HORAS_POR_DIA = {
        "horas_lun": Horario.Dia.LUNES,
        "horas_mar": Horario.Dia.MARTES,
        "horas_mie": Horario.Dia.MIERCOLES,
        "horas_jue": Horario.Dia.JUEVES,
        "horas_vie": Horario.Dia.VIERNES,
    }

    horas_lun = forms.IntegerField(
        label="Lunes",
        min_value=0,
        required=False,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
    )
    horas_mar = forms.IntegerField(
        label="Martes",
        min_value=0,
        required=False,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
    )
    horas_mie = forms.IntegerField(
        label="Miércoles",
        min_value=0,
        required=False,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
    )
    horas_jue = forms.IntegerField(
        label="Jueves",
        min_value=0,
        required=False,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
    )
    horas_vie = forms.IntegerField(
        label="Viernes",
        min_value=0,
        required=False,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
    )

    class Meta:
        model = Designacion
        fields = [
            "cargo",
            "espacio_curricular",
            "unidad_educativa",
            "situacion_revista",
            "anio_curso",
            "division_seccion",
            "turno",
            "hs_catedra",
            "jornada",
            "especialidad",
            "disp_alta_nro",
            "sello_regional_as",
            "motivo",
            "norma_tipo",
            "norma_numero",
            "norma_anio",
            "organismo_emisor",
            "desde",
            "hasta",
            "pof",
            "anio_pof",
            "novedad",
            "observaciones",
        ]
        widgets = {
            "cargo": forms.Select(attrs={"class": "form-select"}),
            "espacio_curricular": forms.Select(attrs={"class": "form-select"}),
            "unidad_educativa": forms.Select(attrs={"class": "form-select"}),
            "situacion_revista": forms.Select(attrs={"class": "form-select"}),
            "anio_curso": forms.TextInput(attrs={"class": "form-control"}),
            "division_seccion": forms.TextInput(attrs={"class": "form-control"}),
            "turno": forms.TextInput(attrs={"class": "form-control"}),
            "hs_catedra": forms.NumberInput(
                attrs={"class": "form-control", "min": "0"}
            ),
            "jornada": forms.TextInput(attrs={"class": "form-control"}),
            "especialidad": forms.Select(attrs={"class": "form-select"}),
            "disp_alta_nro": forms.TextInput(attrs={"class": "form-control"}),
            "sello_regional_as": forms.TextInput(attrs={"class": "form-control"}),
            "motivo": forms.Select(attrs={"class": "form-select"}),
            "norma_tipo": forms.Select(attrs={"class": "form-select"}),
            "norma_numero": forms.TextInput(attrs={"class": "form-control"}),
            "norma_anio": forms.NumberInput(
                attrs={"class": "form-control", "min": "1900", "max": "2200"}
            ),
            "organismo_emisor": forms.TextInput(attrs={"class": "form-control"}),
            "desde": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "hasta": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "pof": forms.TextInput(attrs={"class": "form-control"}),
            "anio_pof": forms.NumberInput(
                attrs={"class": "form-control", "min": "1900", "max": "2200"}
            ),
            "novedad": forms.TextInput(attrs={"class": "form-control"}),
            "observaciones": forms.Textarea(
                attrs={"class": "form-control", "rows": 3}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cargo"].queryset = Cargo.objects.order_by("descripcion")
        self.fields["espacio_curricular"].queryset = (
            EspacioCurricular.objects.select_related("carrera")
            .order_by("carrera__nombre", "nombre")
        )
        self.fields["unidad_educativa"].queryset = UnidadEducativa.objects.order_by(
            "descripcion", "numero"
        )

        if self.instance and self.instance.pk:
            horarios = {
                horario.dia: horario.horas_catedra
                for horario in self.instance.horarios.all()
            }
            for nombre, dia in self.HORAS_POR_DIA.items():
                self.fields[nombre].initial = horarios.get(dia, 0)

    def clean(self):
        cleaned_data = super().clean()
        desde = cleaned_data.get("desde")
        hasta = cleaned_data.get("hasta")
        if desde and hasta and hasta < desde:
            self.add_error("hasta", "La fecha de finalización no puede ser anterior al inicio.")
        return cleaned_data

    @transaction.atomic
    def save(self, commit=True):
        designacion = super().save(commit=commit)
        if not commit:
            return designacion

        for field_name, dia in self.HORAS_POR_DIA.items():
            horas = self.cleaned_data.get(field_name) or 0
            if horas:
                Horario.objects.update_or_create(
                    designacion=designacion,
                    dia=dia,
                    defaults={"horas_catedra": horas},
                )
            else:
                Horario.objects.filter(
                    designacion=designacion,
                    dia=dia,
                ).delete()

        return designacion


class NuevaDesignacionForm(DesignacionForm):
    persona = forms.ModelChoiceField(
        queryset=Persona.objects.filter(activa=True).order_by("apellido_nombre"),
        label="Legajo del agente",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    @transaction.atomic
    def save(self, commit=True):
        self.instance.persona = self.cleaned_data["persona"]
        return super().save(commit=commit)
