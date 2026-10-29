from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password

from asistencias.models import EventoAsistencia
from licencias.models import LicenciaArticulo
from personal.models import Carrera, EspacioCurricular

from .models import ParametroSistema
from .selectors import ORIGEN_AUSENCIAS, ORIGEN_LICENCIAS, ORIGEN_TODOS
from .roles import ROLES

User = get_user_model()


class ParametroSistemaForm(forms.ModelForm):
    class Meta:
        model = ParametroSistema
        fields = ["codigo_oficina", "nombre_oficina", "ciclo_lectivo"]
        widgets = {
            "codigo_oficina": forms.TextInput(attrs={"class": "form-control"}),
            "nombre_oficina": forms.TextInput(attrs={"class": "form-control"}),
            "ciclo_lectivo": forms.NumberInput(attrs={"class": "form-control"}),
        }


class FiltroBitacoraForm(forms.Form):
    usuario = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        empty_label="Todos",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    accion = forms.ChoiceField(
        label="Acción",
        required=False,
        choices=[("", "Todas")] + list(EventoAsistencia.Accion.choices),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    dni = forms.CharField(
        label="DNI del docente",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    desde = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    hasta = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo usuarios que registraron algún evento.
        self.fields["usuario"].queryset = (
            User.objects.filter(eventos_asistencia__isnull=False)
            .distinct()
            .order_by("username")
        )

    def clean(self):
        datos = super().clean()
        desde, hasta = datos.get("desde"), datos.get("hasta")
        if desde and hasta and desde > hasta:
            raise forms.ValidationError("La fecha «desde» no puede ser posterior a «hasta».")
        return datos


# ───────────── Usuarios y roles (RF-19) ─────────────




class UsuarioForm(forms.ModelForm):
    rol = forms.ModelChoiceField(
        queryset=Group.objects.filter(name__in=ROLES).order_by("name"),
        empty_label=None,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    password1 = forms.CharField(
        label="Contraseña",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Repetir contraseña",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "is_active"]
        labels = {
            "username": "Usuario",
            "first_name": "Nombre",
            "last_name": "Apellido",
            "email": "Correo electrónico",
            "is_active": "Activo",
        }
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, usuario_actual=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.creando = self.instance.pk is None
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True

        if self.creando:
            self.fields["password1"].required = True
            self.fields["password2"].required = True
            self.fields["is_active"].initial = True
        else:
            actual = self.instance.groups.filter(name__in=ROLES).first()
            self.fields["rol"].initial = actual
            self.fields["password1"].help_text = "Dejala vacía para no cambiarla."

        # Evita que alguien se quite a sí mismo el acceso o el rol.
        if usuario_actual is not None and self.instance.pk == usuario_actual.pk:
            for nombre in ("is_active", "rol"):
                self.fields[nombre].disabled = True

    def clean(self):
        datos = super().clean()
        p1, p2 = datos.get("password1"), datos.get("password2")
        if p1 or p2:
            if p1 != p2:
                self.add_error("password2", "Las contraseñas no coinciden.")
            else:
                try:
                    validate_password(p1, self.instance)
                except forms.ValidationError as error:
                    self.add_error("password1", error)
        return datos

    def save(self, commit=True):
        usuario = super().save(commit=False)
        if self.cleaned_data.get("password1"):
            usuario.set_password(self.cleaned_data["password1"])
        usuario.save()
        # Reemplaza solo el rol; otros grupos del usuario quedan como están.
        usuario.groups.remove(*Group.objects.filter(name__in=ROLES))
        usuario.groups.add(self.cleaned_data["rol"])
        return usuario


# ───────────── Consultas (RF-17) ─────────────



ORIGENES = [
    (ORIGEN_TODOS, "Licencias y ausencias"),
    (ORIGEN_LICENCIAS, "Solo licencias"),
    (ORIGEN_AUSENCIAS, "Solo ausencias y permisos"),
]


class FiltroConsultaForm(forms.Form):
    JUSTIFICA = [
        ("", "Todas"),
        ("si", "Justificadas"),
        ("no", "No justificadas"),
        ("pendiente", "Sin definir"),
    ]

    dni = forms.CharField(label="DNI", required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    apellido = forms.CharField(label="Apellido o nombre", required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    carrera = forms.ModelChoiceField(
        queryset=Carrera.objects.all(),
        required=False,
        empty_label="Todas",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    espacio_curricular = forms.ModelChoiceField(
        label="Materia",
        queryset=EspacioCurricular.objects.none(),
        required=False,
        empty_label="Todas",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    origen = forms.ChoiceField(
        label="Mostrar",
        required=False,
        initial=ORIGEN_TODOS,
        choices=ORIGENES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    desde = forms.DateField(label="Desde", required=False, widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))
    hasta = forms.DateField(label="Hasta", required=False, widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))
    tipo_licencia = forms.ChoiceField(label="Tipo de licencia", required=False, widget=forms.Select(attrs={"class": "form-select"}))
    disp_tipo = forms.CharField(label="Instrumento (tipo)", required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    disp_numero = forms.CharField(label="Instrumento (número)", required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    disp_anio = forms.IntegerField(label="Instrumento (año)", required=False, min_value=1900, max_value=2100, widget=forms.NumberInput(attrs={"class": "form-control"}))
    justifica = forms.ChoiceField(label="Justificación", required=False, choices=JUSTIFICA, widget=forms.Select(attrs={"class": "form-select"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tipos = (
            LicenciaArticulo.objects.order_by("tipo_licencia")
            .values_list("tipo_licencia", flat=True)
            .distinct()
        )
        self.fields["tipo_licencia"].choices = [("", "Todos")] + [(t, t) for t in tipos]
        self.fields["espacio_curricular"].queryset = (
            EspacioCurricular.objects.filter(activo=True)
            .select_related("carrera")
            .order_by("carrera__nombre", "nombre")
        )

    def clean(self):
        datos = super().clean()
        desde, hasta = datos.get("desde"), datos.get("hasta")
        if desde and hasta and desde > hasta:
            raise forms.ValidationError("La fecha «desde» no puede ser posterior a «hasta».")
        carrera, espacio = datos.get("carrera"), datos.get("espacio_curricular")
        if carrera and espacio and espacio.carrera_id != carrera.pk:
            self.add_error("espacio_curricular", "La materia no pertenece a la carrera elegida.")
        return datos


# ───────────── Alertas (RF-18) ─────────────

class FiltroAlertasForm(forms.Form):
    UMBRALES = [(50, "50 %"), (70, "70 %"), (80, "80 %"), (90, "90 %"), (100, "Solo agotados")]

    anio = forms.IntegerField(
        label="Año",
        min_value=2000,
        max_value=2100,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )
    umbral = forms.TypedChoiceField(
        label="Avisar desde",
        choices=UMBRALES,
        coerce=int,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
