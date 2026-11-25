from django import forms
from django.db import transaction
from django.db.models import Q

from datetime import date, datetime

from .models import (
    FECHA_SIN_INICIO,
    TEXTO_SIN_INICIO,
    TEXTO_SIN_TERMINO,
    Cargo,
    Carrera,
    Designacion,
    EspacioCurricular,
    Horario,
    Persona,
    TipoInstrumentoLegal,
    UnidadEducativa,
    problema_de_horas,
)


def _sin_espacios(texto):
    return " ".join((texto or "").upper().split())


def interpretar_fecha_de_vigencia(texto):
    """
    RN-09: convierte lo escrito en Desde/Hasta. Devuelve una fecha, la cadena
    especial («SIN INICIO» / «SIN TERMINO») o None si está vacío. Acepta
    dd/mm/aaaa y AAAA-MM-DD. Lanza ValueError si no se entiende.
    """
    texto = (texto or "").strip()

    if not texto:
        return None

    normalizado = _sin_espacios(texto).replace("É", "E")

    if normalizado in (TEXTO_SIN_INICIO, TEXTO_SIN_TERMINO):
        return normalizado

    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue

    raise ValueError(texto)


class FechaDeVigenciaField(forms.CharField):
    """
    Campo de vigencia de una designación (RN-09): una fecha estándar o la
    cadena especial que le corresponde (`especial`).
    """

    def __init__(self, *, especial, **kwargs):
        self.especial = especial
        kwargs.setdefault(
            "widget",
            forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": f"dd/mm/aaaa o {especial}",
                    "list": f"opciones-{especial.replace(' ', '-').lower()}",
                    "autocomplete": "off",
                }
            ),
        )
        super().__init__(**kwargs)

    def to_python(self, value):
        if isinstance(value, date):
            return value

        try:
            valor = interpretar_fecha_de_vigencia(super().to_python(value))
        except ValueError:
            raise forms.ValidationError(
                f"Ingrese una fecha (dd/mm/aaaa) o {self.especial}."
            )

        if isinstance(valor, str) and valor != self.especial:
            raise forms.ValidationError(
                f"En este campo la cadena especial es {self.especial}."
            )

        return valor

    def prepare_value(self, value):
        if isinstance(value, date):
            if value == FECHA_SIN_INICIO:
                return TEXTO_SIN_INICIO
            return value.strftime("%d/%m/%Y")
        return value


class TipoInstrumentoLegalForm(forms.ModelForm):
    class Meta:
        model = TipoInstrumentoLegal
        fields = ["nombre", "activo"]
        widgets = {
            "nombre": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Ej.: Resolución"}
            ),
            "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class CargoForm(forms.ModelForm):
    class Meta:
        model = Cargo
        fields = ["codigo", "descripcion", "es_docente", "activo"]
        widgets = {
            "codigo": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "inputmode": "numeric",
                    "pattern": r"\d+",
                    "placeholder": "Ej.: 166",
                }
            ),
            "descripcion": forms.TextInput(attrs={"class": "form-control"}),
            "es_docente": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # El código es la clave del cargo: cambiarlo al editar crearía un
        # cargo nuevo en vez de renombrar el existente, así que queda fijo.
        if not self.instance._state.adding:
            self.fields["codigo"].disabled = True


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
    """Una materia se carga una sola vez y se marca en qué carreras se dicta."""

    class Meta:
        model = EspacioCurricular
        fields = ["nombre", "carreras", "activo"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control"}),
            "carreras": forms.CheckboxSelectMultiple(),
            "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {"carreras": "Carreras en las que se dicta"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["carreras"].queryset = Carrera.objects.order_by("nombre")

    def clean_nombre(self):
        nombre = " ".join((self.cleaned_data.get("nombre") or "").split())
        existentes = EspacioCurricular.objects.filter(nombre__iexact=nombre)

        if self.instance.pk:
            # Renombrar no puede pisar otra materia que ya existe.
            if existentes.exclude(pk=self.instance.pk).exists():
                raise forms.ValidationError("Ya hay otra materia con ese nombre.")
            return nombre

        existente = existentes.first()
        if existente is not None:
            # Alta de una materia que ya existe: no se repite; se le suman
            # las carreras elegidas (una materia puede estar en varias).
            self.instance = existente
            self.fusion = True
            return existente.nombre
        return nombre

    def clean(self):
        datos = super().clean()
        # Al editar, no se puede quitar una carrera que usan designaciones
        # activas: quedarían con una carrera que la materia ya no tiene.
        if self.instance.pk and not getattr(self, "fusion", False) and "carreras" in datos:
            quitadas = set(self.instance.carreras.all()) - set(datos["carreras"])
            en_uso = sorted({
                designacion.carrera.nombre
                for designacion in Designacion.objects.filter(
                    espacio_curricular=self.instance, carrera__in=quitadas, activo=True
                ).select_related("carrera")
            })
            if en_uso:
                self.add_error(
                    "carreras",
                    f"No se puede quitar {', '.join(en_uso)}: hay designaciones activas de "
                    "esta materia en esa carrera. Primero cambialas o dalas de baja.",
                )
        return datos

    @transaction.atomic
    def save(self, commit=True):
        fusion = getattr(self, "fusion", False)
        if fusion:
            # Se lee de nuevo y bloqueado: si alguien la editó mientras tanto,
            # se suma sobre lo último guardado.
            actual = EspacioCurricular.objects.select_for_update().get(pk=self.instance.pk)
            previas = list(actual.carreras.all())
            # Sumar carreras nunca desactiva una materia que ya existía.
            self.instance.activo = actual.activo or self.cleaned_data.get("activo", True)

        materia = super().save(commit=commit)

        if fusion and commit:
            materia.carreras.add(*previas)
            nuevas = [c.nombre for c in self.cleaned_data["carreras"] if c not in previas]
            self.aviso = (
                f"«{materia.nombre}» ya existía: se le sumó {', '.join(nuevas)}."
                if nuevas
                else f"«{materia.nombre}» ya estaba en esas carreras."
            )
        return materia


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
        queryset=EspacioCurricular.objects.filter(activo=True).order_by("nombre"),
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
        labels = {"apellido_nombre": "Nombre y Apellido"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["apellido_nombre"].required = False
        if self.instance and self.instance.pk:
            self.fields["dni"].disabled = True
            self.fields["dni"].help_text = "El DNI identifica el legajo y no se modifica."

    def clean(self):
        cleaned_data = super().clean()
        nombre_completo = (cleaned_data.get("apellido_nombre") or "").strip()
        cleaned_data["apellido_nombre"] = nombre_completo
        if not nombre_completo:
            self.add_error(
                "apellido_nombre",
                "Ingrese el nombre y apellido del agente.",
            )
            return cleaned_data

        if "," in nombre_completo:
            apellido, nombres = (
                parte.strip() for parte in nombre_completo.split(",", 1)
            )
        else:
            apellido, nombres = nombre_completo, ""
        self.instance.apellido = apellido
        self.instance.nombres = nombres
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

    # RN-09: Desde y Hasta admiten una fecha o SIN INICIO / SIN TERMINO.
    desde = FechaDeVigenciaField(especial=TEXTO_SIN_INICIO, label="Desde")
    hasta = FechaDeVigenciaField(
        especial=TEXTO_SIN_TERMINO, label="Hasta", required=False
    )
    # RF-05: el tipo de norma sale del catálogo de instrumentos legales.
    norma_tipo = forms.ChoiceField(
        label="Tipo de norma",
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = Designacion
        fields = [
            "cargo",
            "espacio_curricular",
            "carrera",
            "unidad_educativa",
            "situacion_revista",
            "anio_curso",
            "division_seccion",
            "turno",
            "hs_catedra",
            "reemplaza",
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
            # Sin «especialidad», «es_suplencia» ni «plazo_indeterminado»: la
            # suplencia sale de la situación de revista (Suplente) y el plazo
            # indeterminado de escribir SIN TERMINO en Hasta (ver clean()).
            # Las columnas siguen en la base y se completan solas.
        ]
        labels = {
            "hs_catedra": "Horas cátedra nombradas",
        }
        widgets = {
            "cargo": forms.Select(attrs={"class": "form-select"}),
            "espacio_curricular": forms.Select(attrs={"class": "form-select"}),
            "carrera": forms.Select(attrs={"class": "form-select"}),
            "unidad_educativa": forms.Select(attrs={"class": "form-select"}),
            "situacion_revista": forms.Select(attrs={"class": "form-select"}),
            "anio_curso": forms.TextInput(attrs={"class": "form-control"}),
            "division_seccion": forms.TextInput(attrs={"class": "form-control"}),
            "turno": forms.TextInput(attrs={"class": "form-control"}),
            "hs_catedra": forms.NumberInput(
                attrs={"class": "form-control", "min": "1"}
            ),
            "reemplaza": forms.Select(attrs={"class": "form-select"}),
            "disp_alta_nro": forms.TextInput(attrs={"class": "form-control"}),
            "sello_regional_as": forms.TextInput(attrs={"class": "form-control"}),
            "norma_numero": forms.TextInput(attrs={"class": "form-control"}),
            "norma_anio": forms.NumberInput(
                attrs={"class": "form-control", "min": "1900", "max": "2200"}
            ),
            "organismo_emisor": forms.TextInput(attrs={"class": "form-control"}),
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
        self.fields["norma_tipo"].choices = TipoInstrumentoLegal.opciones(
            actual=self.instance.norma_tipo if self.instance else ""
        )
        if self.instance and self.instance.pk:
            self.initial["desde"] = self.instance.desde_texto
            self.initial["hasta"] = self.instance.hasta_texto
        self.fields["cargo"].queryset = Cargo.objects.order_by("descripcion")
        espacios = EspacioCurricular.objects.prefetch_related("carreras").order_by(
            "nombre"
        )
        self.fields["espacio_curricular"].queryset = espacios
        self.fields["carrera"].queryset = Carrera.objects.order_by("nombre")
        self.fields["carrera"].help_text = (
            "Si la materia está en una sola carrera se completa sola."
        )
        # Para la pantalla: qué carreras ofrece cada materia.
        self.carreras_por_materia = {
            str(espacio.pk): [carrera.pk for carrera in espacio.carreras.all()]
            for espacio in espacios
        }
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
        sin_termino = hasta == TEXTO_SIN_TERMINO

        # RN-09: cadenas especiales. SIN INICIO se guarda con la fecha
        # convenida y la marca `sin_inicio`; SIN TERMINO deja `hasta` vacío.
        self.instance.sin_inicio = desde == TEXTO_SIN_INICIO
        if desde == TEXTO_SIN_INICIO:
            desde = cleaned_data["desde"] = FECHA_SIN_INICIO
        if sin_termino:
            hasta = cleaned_data["hasta"] = None

        # La suplencia sale de la situación de revista: no hace falta una
        # marca aparte. Una suplencia SIN TERMINO es de plazo indeterminado.
        es_suplencia = (
            cleaned_data.get("situacion_revista") == Designacion.Situacion.SUPLENTE
        )
        self.instance.es_suplencia = es_suplencia
        self.instance.plazo_indeterminado = es_suplencia and sin_termino
        if es_suplencia and hasta is None and not sin_termino and "hasta" not in self.errors:
            self.add_error(
                "hasta",
                "Para una suplencia indique la fecha de cese o escriba "
                "SIN TERMINO (plazo indeterminado).",
            )
            # El modelo repetiría el mismo aviso con otras palabras.
            self.instance.plazo_indeterminado = True

        reemplaza = cleaned_data.get("reemplaza")
        if desde and hasta and hasta < desde:
            self.add_error("hasta", "La fecha de finalización no puede ser anterior al inicio.")
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

        # Control de horas: el horario semanal tiene que sumar las horas
        # cátedra nombradas (misma regla que la importación y las alertas).
        if "hs_catedra" not in self.errors:
            problema = problema_de_horas(
                cleaned_data.get("hs_catedra"),
                [cleaned_data.get(campo) or 0 for campo in self.HORAS_POR_DIA],
            )
            if problema:
                self.add_error("hs_catedra", problema)
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
