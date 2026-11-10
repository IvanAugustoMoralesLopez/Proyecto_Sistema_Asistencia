from django import forms
from django.db import transaction
from django.db.models import Q

from .models import (
    Cargo,
    Carrera,
    Designacion,
    EspacioCurricular,
    Horario,
    Persona,
    UnidadEducativa,
)


class CargoForm(forms.ModelForm):
    class Meta:
        model = Cargo
        fields = ["codigo", "descripcion", "es_docente", "activo"]
        widgets = {
            "codigo": forms.TextInput(attrs={"class": "form-control"}),
            "descripcion": forms.TextInput(attrs={"class": "form-control"}),
            "es_docente": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class CarreraForm(forms.ModelForm):
    class Meta:
        model = Carrera
        fields = [
            "nombre",
            "plan_estudio",
            "anio_plan",
            "activa",
            "plan_vigente",
            "plan_vigente_desde",
            "plan_vigente_hasta",
        ]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control"}),
            "plan_estudio": forms.TextInput(attrs={"class": "form-control"}),
            "anio_plan": forms.NumberInput(attrs={"class": "form-control"}),
            "activa": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "plan_vigente": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
            "plan_vigente_desde": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "plan_vigente_hasta": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
        }


class EspacioCurricularForm(forms.ModelForm):
    class Meta:
        model = EspacioCurricular
        fields = ["nombre", "carrera", "activo"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control"}),
            "carrera": forms.Select(attrs={"class": "form-select"}),
            "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class BuscarLegajoForm(forms.Form):
    dni = forms.CharField(
        required=False,
        label="DNI o apellido/nombre",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Buscar por DNI, apellido o nombre",
                "list": "legajos-autocompletado",
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
            "apellido",
            "nombres",
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
            "apellido": forms.TextInput(attrs={"class": "form-control"}),
            "nombres": forms.TextInput(attrs={"class": "form-control"}),
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
        self.fields["apellido_nombre"].required = False
        if self.instance and self.instance.pk:
            self.fields["dni"].disabled = True
            self.fields["dni"].help_text = "El DNI identifica el legajo y no se modifica."

    def clean(self):
        cleaned_data = super().clean()
        apellido = (cleaned_data.get("apellido") or "").strip()
        nombres = (cleaned_data.get("nombres") or "").strip()
        nombre_completo = cleaned_data.get("apellido_nombre", "").strip()

        if self.instance and self.instance.pk:
            cambios_componentes = (
                apellido != self.instance.apellido or nombres != self.instance.nombres
            )
            cambio_nombre_completo = (
                nombre_completo != self.instance.apellido_nombre
            )
        else:
            cambios_componentes = bool(apellido or nombres)
            cambio_nombre_completo = bool(nombre_completo)

        if cambios_componentes:
            nombre_completo = ", ".join(
                parte for parte in (apellido, nombres) if parte
            )
            cleaned_data["apellido_nombre"] = nombre_completo
        elif cambio_nombre_completo and nombre_completo:
            if "," in nombre_completo:
                apellido, nombres = (
                    parte.strip() for parte in nombre_completo.split(",", 1)
                )
            else:
                apellido, nombres = nombre_completo, ""
            cleaned_data["apellido"] = apellido
            cleaned_data["nombres"] = nombres

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
            "reemplaza",
            "especialidad",
            "disp_alta_nro",
            "sello_regional_as",
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
            "es_suplencia",
            "plazo_indeterminado",
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
            "reemplaza": forms.Select(attrs={"class": "form-select"}),
            "especialidad": forms.Select(attrs={"class": "form-select"}),
            "disp_alta_nro": forms.TextInput(attrs={"class": "form-control"}),
            "sello_regional_as": forms.TextInput(attrs={"class": "form-control"}),
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
            "es_suplencia": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
            "plazo_indeterminado": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
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
        reemplazos = Designacion.objects.filter(activo=True)
        if self.instance and self.instance.pk:
            reemplazos = reemplazos.exclude(pk=self.instance.pk)
            if self.instance.reemplaza_id:
                reemplazos = Designacion.objects.filter(
                    Q(activo=True) | Q(pk=self.instance.reemplaza_id)
                ).exclude(pk=self.instance.pk)
            if self.instance.persona_id:
                reemplazos = reemplazos.exclude(
                    persona_id=self.instance.persona_id
                )
        self.fields["reemplaza"].queryset = reemplazos.select_related(
            "persona", "cargo"
        ).order_by("persona__apellido_nombre", "desde")

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
        plazo_indeterminado = cleaned_data.get("plazo_indeterminado")
        reemplaza = cleaned_data.get("reemplaza")
        if desde and hasta and hasta < desde:
            self.add_error("hasta", "La fecha de finalización no puede ser anterior al inicio.")
        if plazo_indeterminado:
            cleaned_data["hasta"] = None
        if (
            reemplaza
            and self.instance.reemplaza_id != reemplaza.pk
            and desde
            and not reemplaza.vigente_en(desde)
        ):
            self.add_error(
                "reemplaza",
                "La designación reemplazada no está vigente al inicio de la suplencia.",
            )
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
        widget=forms.HiddenInput(),
    )

    def clean(self):
        cleaned_data = super().clean()
        persona = cleaned_data.get("persona")
        reemplaza = cleaned_data.get("reemplaza")
        if persona and reemplaza and persona.pk == reemplaza.persona_id:
            self.add_error(
                "reemplaza",
                "El docente suplente no puede reemplazarse a sí mismo.",
            )
        return cleaned_data

    @transaction.atomic
    def save(self, commit=True):
        self.instance.persona = self.cleaned_data["persona"]
        return super().save(commit=commit)
