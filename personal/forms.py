from django import forms

from .models import Cargo, EspacioCurricular


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
        queryset=EspacioCurricular.objects.filter(activo=True).select_related("carrera").order_by("carrera__nombre", "nombre"),
        required=False,
        empty_label="Todos los espacios",
        label="Espacio curricular",
        widget=forms.Select(attrs={"class": "form-select"}),
    )


class LegajoDocenteForm(forms.Form):
    dni = forms.CharField(
        label="DNI",
        max_length=8,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    nombre_docente = forms.CharField(
        label="Nombre docente",
        max_length=120,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    sexo = forms.ChoiceField(
        label="Sexo",
        choices=[("", "Seleccione"), ("M", "Masculino"), ("F", "Femenino")],
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    situacion_revista = forms.ChoiceField(
        label="Situación de revista",
        choices=[
            ("", "Seleccione"),
            ("Titular", "Titular"),
            ("Interino", "Interino"),
            ("Suplente", "Suplente"),
        ],
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
