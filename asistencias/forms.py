from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from personal.models import Designacion, EspacioCurricular
from licencias.models import LicenciaOtorgada

from .models import (
    DiaNoLaborable,
    RegistroAsistencia,
    MarcaAsistencia,
    licencia_cubre_fecha,
)
from .services import (
    ANIO_MAXIMO,
    ANIO_MINIMO,
    MOTIVO_MINIMO,
    TRANSICIONES_JUSTIFICACION,
    validar_dia_laborable,
)


class SelectMarca(forms.Select):
    """
    Combo de marcas que publica en cada opción si la marca exige horas o
    licencia (`data-horas`, `data-licencia`).

    Así la pantalla puede habilitar o completar esos campos sin repetir en
    JavaScript las reglas del catálogo (RF-08), que viven en la base.
    """

    def create_option(self, name, value, *args, **kwargs):
        opcion = super().create_option(name, value, *args, **kwargs)
        marca = getattr(value, "instance", None)

        if marca is not None:
            opcion["attrs"]["data-horas"] = "1" if marca.requiere_horas else "0"
            opcion["attrs"]["data-licencia"] = (
                "1" if marca.requiere_licencia else "0"
            )

        return opcion


def _etiqueta_designacion(designacion):
    """«APELLIDO, Nombre (DNI) — Cargo — Espacio»: identifica la fila sin dudas."""
    partes = [
        f"{designacion.persona.apellido_nombre} ({designacion.persona.dni})",
        designacion.cargo.descripcion,
    ]

    if designacion.espacio_curricular_id:
        partes.append(designacion.espacio_curricular.nombre)

    return " — ".join(partes)


def _etiqueta_licencia(licencia):
    """«Art. X · Docente · desde dd/mm/aaaa»."""
    hasta = f" al {licencia.hasta:%d/%m/%Y}" if licencia.hasta else ""
    return (
        f"{licencia.articulo.articulo} · "
        f"{licencia.designacion.persona.apellido_nombre} · "
        f"{licencia.desde:%d/%m/%Y}{hasta}"
    )


def _aplicar_clases_bootstrap(fields):
    for field in fields.values():
        clase = (
            "form-select"
            if isinstance(field.widget, forms.Select)
            else "form-control"
        )
        field.widget.attrs.setdefault("class", clase)


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
            "marca": SelectMarca,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        designaciones_vigentes = Designacion.objects.filter(
            activo=True,
            persona__activa=True,
        )
        marcas_vigentes = MarcaAsistencia.vigentes()

        # Si se edita un registro cuya designación o marca ya no está
        # vigente (p. ej. el docente cesó), igual debe aparecer seleccionada
        # en el combo; de lo contrario el formulario la rechaza como
        # "opción no válida" aunque no se la haya cambiado.
        if self.instance and self.instance.pk:
            if self.instance.designacion_id:
                designaciones_vigentes = designaciones_vigentes | Designacion.objects.filter(
                    pk=self.instance.designacion_id
                )
            if self.instance.marca_id:
                marcas_vigentes = marcas_vigentes | MarcaAsistencia.objects.filter(
                    pk=self.instance.marca_id
                )

        self.fields["designacion"].queryset = designaciones_vigentes.select_related(
            "persona",
            "cargo",
            "espacio_curricular",
        ).distinct()

        self.fields["marca"].queryset = marcas_vigentes.distinct()

        # El combo de licencias traía todas las licencias del sistema, de
        # todos los años: se acota a las de designaciones vigentes (más la
        # del registro que se está editando, para que siga apareciendo).
        licencias = LicenciaOtorgada.objects.filter(
            designacion__activo=True,
            designacion__persona__activa=True,
        )

        if self.instance and self.instance.pk and self.instance.licencia_id:
            licencias = licencias | LicenciaOtorgada.objects.filter(
                pk=self.instance.licencia_id
            )

        self.fields["licencia"].queryset = (
            licencias.select_related("designacion__persona", "articulo")
            .distinct()
            .order_by("-desde", "-pk")
        )
        self.fields["licencia"].required = False

        # Etiquetas con DNI: en una lista larga es lo que identifica al
        # docente sin ambigüedad.
        self.fields["designacion"].label_from_instance = _etiqueta_designacion
        self.fields["licencia"].label_from_instance = _etiqueta_licencia

        _aplicar_clases_bootstrap(self.fields)

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

        validar_dia_laborable(fecha)

        return fecha

    def clean(self):
        cleaned = super().clean()

        designacion = cleaned.get("designacion")
        marca = cleaned.get("marca")
        fecha = cleaned.get("fecha")
        licencia = cleaned.get("licencia")
        observaciones = cleaned.get("observaciones", "")
        horas_inasistidas = cleaned.get("horas_inasistidas")

        if (
            marca
            and marca.requiere_observacion
            and not observaciones.strip()
        ):
            self.add_error(
                "observaciones",
                "Esta marca requiere una observación.",
            )

        if marca:
            if marca.requiere_horas:
                if not horas_inasistidas or horas_inasistidas <= Decimal("0"):
                    self.add_error(
                        "horas_inasistidas",
                        "Esta marca requiere horas inasistidas mayores a cero.",
                    )
            else:
                cleaned["horas_inasistidas"] = Decimal("0")

            if marca.requiere_licencia and not licencia:
                self.add_error(
                    "licencia",
                    "Esta marca requiere una licencia aprobada vinculada.",
                )

        if licencia and designacion:
            if licencia.designacion_id != designacion.pk:
                self.add_error(
                    "licencia",
                    "La licencia no corresponde a la designación elegida.",
                )

            if fecha and not licencia_cubre_fecha(licencia, fecha):
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
        queryset=MarcaAsistencia.vigentes(),
        empty_label="Todas las marcas",
    )
    espacio_curricular = forms.ModelChoiceField(
        required=False,
        label="Materia",
        queryset=EspacioCurricular.objects.filter(activo=True)
        .select_related("carrera")
        .order_by("carrera__nombre", "nombre"),
        empty_label="Todas las materias",
    )
    estado_registro = forms.ChoiceField(
        required=False,
        label="Estado",
        choices=[("", "Todos los estados")]
        + RegistroAsistencia.Estado.choices,
    )
    estado_justificacion = forms.ChoiceField(
        required=False,
        label="Justificación",
        choices=[("", "Todos los estados")]
        + RegistroAsistencia.EstadoJustificacion.choices,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _aplicar_clases_bootstrap(self.fields)

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


class FiltroRecepcionForm(FiltroAsistenciaForm):
    """Filtro de la pantalla de recepción: por defecto, los pendientes."""

    PENDIENTES = "PENDIENTES"
    TODAS = "TODAS"

    estado_justificacion = forms.ChoiceField(
        required=False,
        label="Justificación",
        choices=[
            (PENDIENTES, "Pendientes (injustificadas y en trámite)"),
            *RegistroAsistencia.EstadoJustificacion.choices[1:],
            (TODAS, "Todas las inasistencias"),
        ],
    )


class RecepcionFormularioForm(forms.Form):
    estado_justificacion = forms.ChoiceField(label="Nuevo estado")
    nro_formulario = forms.CharField(
        required=False,
        max_length=30,
        label="N° de formulario",
    )
    fecha_recepcion = forms.DateField(
        required=False,
        label="Fecha de recepción",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    motivo = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Obligatorio al rechazar un formulario.",
    )

    def __init__(self, *args, registro, **kwargs):
        super().__init__(*args, **kwargs)

        permitidos = TRANSICIONES_JUSTIFICACION.get(
            registro.estado_justificacion, set()
        )
        self.fields["estado_justificacion"].choices = [
            (valor, etiqueta)
            for valor, etiqueta in RegistroAsistencia.EstadoJustificacion.choices
            if valor in permitidos
        ]
        self.fields["fecha_recepcion"].initial = timezone.localdate()

        _aplicar_clases_bootstrap(self.fields)

    def clean_fecha_recepcion(self):
        fecha = self.cleaned_data["fecha_recepcion"]

        if fecha and fecha > timezone.localdate():
            raise ValidationError(
                "La fecha de recepción no puede ser futura."
            )

        return fecha

    def clean(self):
        cleaned = super().clean()
        estado = cleaned.get("estado_justificacion")

        if not estado:
            return cleaned

        if (
            estado == RegistroAsistencia.EstadoJustificacion.INJUSTIFICADA
        ):
            if len(cleaned.get("motivo", "").strip()) < MOTIVO_MINIMO:
                self.add_error(
                    "motivo",
                    "Indicá el motivo del rechazo "
                    f"(al menos {MOTIVO_MINIMO} caracteres).",
                )
        elif not cleaned.get("nro_formulario", "").strip():
            self.add_error(
                "nro_formulario",
                "Indicá el número del formulario recepcionado.",
            )

        return cleaned


class CierreMensualForm(forms.Form):
    anio = forms.IntegerField(min_value=2000, max_value=2100)
    mes = forms.IntegerField(min_value=1, max_value=12)


class DiaNoLaborableForm(forms.ModelForm):
    """Alta y edición de un día del calendario escolar (RF-10)."""

    class Meta:
        model = DiaNoLaborable
        fields = ["fecha", "tipo", "descripcion"]
        widgets = {
            # type="date" solo muestra el valor si viene en formato ISO.
            "fecha": forms.DateInput(
                attrs={"type": "date"},
                format="%Y-%m-%d",
            ),
        }
        error_messages = {
            "fecha": {"unique": "Ya hay un día cargado en esa fecha."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _aplicar_clases_bootstrap(self.fields)

    def clean_fecha(self):
        fecha = self.cleaned_data["fecha"]

        if not ANIO_MINIMO <= fecha.year <= ANIO_MAXIMO:
            raise ValidationError(
                f"El año debe estar entre {ANIO_MINIMO} y {ANIO_MAXIMO}."
            )

        return fecha


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


class CargaMasivaCalendarioForm(forms.Form):
    fechas = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "rows": 10,
                "class": "form-control",
                "placeholder": (
                    "Una fecha por línea (dd/mm/aaaa o aaaa-mm-dd).\n"
                    "Opcionalmente, después de la fecha, una descripción.\n\n"
                    "Ejemplo:\n"
                    "01/01/2027 Año Nuevo\n"
                    "24/03/2027 Día de la Memoria\n"
                    "02/04/2027 Día del Veterano"
                ),
            }
        ),
        label="Fechas",
        help_text="Una fecha por línea. Las líneas vacías y las que empiezan con # se ignoran.",
    )
    tipo = forms.ChoiceField(
        choices=DiaNoLaborable.Tipo.choices,
        initial=DiaNoLaborable.Tipo.FERIADO,
        label="Tipo por defecto",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _aplicar_clases_bootstrap(self.fields)


class CopiarCalendarioForm(forms.Form):
    anio_origen = forms.IntegerField(
        min_value=ANIO_MINIMO,
        max_value=ANIO_MAXIMO,
        label="Año de origen",
    )
    anio_destino = forms.IntegerField(
        min_value=ANIO_MINIMO,
        max_value=ANIO_MAXIMO,
        label="Año de destino",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _aplicar_clases_bootstrap(self.fields)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("anio_origen") == cleaned.get("anio_destino"):
            self.add_error(
                "anio_destino",
                "El año destino debe ser distinto del origen.",
            )
        return cleaned