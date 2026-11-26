from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
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
from .services.pendientes import CODIGOS_LICENCIA


class SelectMarca(forms.Select):
    """
    Combo de marcas que publica en cada opción si la marca exige horas o
    licencia (`data-horas`, `data-licencia`) y si es una marca de licencia
    (`data-de-licencia`: LIC y LT, que se completan con la licencia cargada).

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
            opcion["attrs"]["data-de-licencia"] = (
                "1" if marca.codigo in CODIGOS_LICENCIA else "0"
            )

        return opcion


class SelectLicencia(forms.Select):
    """
    Combo de licencias que publica en cada opción la designación a la que
    pertenece y su período (`data-designacion`, `data-desde`, `data-hasta`).

    Con eso la pantalla muestra solo las licencias del docente elegido y
    elige sola la que cubre el día, sin consultar al servidor.
    """

    def create_option(self, name, value, *args, **kwargs):
        opcion = super().create_option(name, value, *args, **kwargs)
        licencia = getattr(value, "instance", None)

        if licencia is not None:
            opcion["attrs"]["data-designacion"] = str(licencia.designacion_id)
            opcion["attrs"]["data-desde"] = licencia.desde.isoformat()
            opcion["attrs"]["data-hasta"] = (
                licencia.hasta.isoformat() if licencia.hasta else ""
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
        labels = {
            "designacion": "Docente (cargo / materia)",
            "fecha": "Día",
            "marca": "¿Asistió?",
            "horas_inasistidas": "Horas que no cubrió",
            "licencia": "Licencia",
            "observaciones": "Nota",
        }
        help_texts = {
            "horas_inasistidas": (
                "Se completan solas con las horas que el docente tiene ese día."
            ),
            "observaciones": "Opcional, salvo que la opción elegida la pida.",
        }
        widgets = {
            # type="date" solo muestra el valor si viene en formato ISO: con
            # el formato de es-ar (dd/mm/aaaa) el Día aparecía vacío al
            # editar y no se podía guardar sin volver a elegirlo.
            "fecha": forms.DateInput(
                attrs={"type": "date", "class": "form-control"},
                format="%Y-%m-%d",
            ),
            "horas_inasistidas": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "0",
                    "step": "0.5",
                }
            ),
            "observaciones": forms.Textarea(
                attrs={"class": "form-control", "rows": 3}
            ),
            "marca": SelectMarca,
            "licencia": SelectLicencia,
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
        # todos los años: se acota a las de designaciones vigentes (más las
        # de la designación del registro que se está editando, para que se
        # puedan elegir aunque esa designación ya se haya dado de baja).
        # La pantalla, además, muestra solo las del docente elegido.
        licencias = LicenciaOtorgada.objects.filter(
            designacion__activo=True,
            designacion__persona__activa=True,
        )

        if self.instance and self.instance.pk:
            licencias = licencias | LicenciaOtorgada.objects.filter(
                Q(pk=self.instance.licencia_id)
                | Q(designacion_id=self.instance.designacion_id)
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

            if (
                marca.requiere_horas
                and horas_inasistidas
                and horas_inasistidas > Decimal("0")
                and designacion
                and fecha
            ):
                from .services.agenda import horas_del_dia

                horas_dia = horas_del_dia(designacion, fecha)
                if horas_dia > Decimal("0") and horas_inasistidas > horas_dia:
                    self.add_error(
                        "horas_inasistidas",
                        f"Superan las {horas_dia} hs cátedra que el docente "
                        "tiene este día según su horario.",
                    )

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
        label="Apellido y nombre del docente",
    )
    desde = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    hasta = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    marca = forms.ModelChoiceField(
        required=False,
        label="¿Asistió?",
        queryset=MarcaAsistencia.vigentes(),
        empty_label="Cualquiera",
    )
    # También las materias dadas de baja (al final): sus asistencias siguen
    # en el historial (RN-03) y tienen que poder buscarse.
    espacio_curricular = forms.ModelChoiceField(
        required=False,
        label="Materia",
        queryset=EspacioCurricular.objects.order_by("-activo", "nombre"),
        empty_label="Todas las materias",
    )
    estado_registro = forms.ChoiceField(
        required=False,
        label="Estado de la carga",
        choices=[
            ("", "Cualquiera"),
            (RegistroAsistencia.Estado.BORRADOR, "Guardado, falta validar"),
            (RegistroAsistencia.Estado.VALIDADO, "Validado"),
        ],
    )
    estado_justificacion = forms.ChoiceField(
        required=False,
        label="Formulario",
        choices=[("", "Cualquiera")]
        + RegistroAsistencia.EstadoJustificacion.choices,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Mismo vocabulario que la pantalla de carga: «Asistió», «Faltó», …
        self.fields["marca"].label_from_instance = lambda marca: marca.etiqueta
        self.fields["espacio_curricular"].label_from_instance = (
            lambda espacio: espacio.nombre
            if espacio.activo
            else f"{espacio.nombre} (dada de baja)"
        )
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
        label="Formulario",
        choices=[
            (PENDIENTES, "Pendientes (sin formulario o en trámite)"),
            *RegistroAsistencia.EstadoJustificacion.choices[1:],
            (TODAS, "Todas las inasistencias"),
        ],
    )


class RecepcionFormularioForm(forms.Form):
    estado_justificacion = forms.ChoiceField(
        label="¿Qué pasó con el certificado?"
    )
    nro_formulario = forms.CharField(
        required=False,
        max_length=30,
        label="N° del formulario en papel",
    )
    fecha_recepcion = forms.DateField(
        required=False,
        label="¿Qué día lo recibiste?",
        # En ISO: con dd/mm/aaaa el navegador no mostraba la fecha de hoy.
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    # RF-09: al recibir el formulario el registro pasa de I a LIC o P.
    nueva_marca = forms.ChoiceField(
        required=False,
        label="¿Qué formulario presentó?",
        choices=[
            ("", "No cambiar la marca"),
            ("LIC", "Licencia médica o especial (LIC)"),
            ("LT", "Largo tratamiento (LT)"),
            ("P", "Permiso (P)"),
        ],
        help_text=(
            "La marca cambia en todas las materias del docente ese día. "
            "El artículo se elige después, en la planilla mensual."
        ),
    )
    motivo = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Motivo",
        help_text="Hay que completarlo solo si rechazás el certificado.",
    )

    def __init__(self, *args, registro, **kwargs):
        super().__init__(*args, **kwargs)
        if registro.marca.codigo != "I":
            # Ya tiene la marca del formulario: no hay nada que elegir.
            del self.fields["nueva_marca"]

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
        # Al justificar, el número del formulario es opcional (RF-09 pide
        # recibir el papel, no registrar su número).

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