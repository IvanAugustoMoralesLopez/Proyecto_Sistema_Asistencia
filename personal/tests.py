from datetime import date

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory, TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse

from .models import (
    Persona,
    Cargo,
    Designacion,
    HistorialDesignacion,
    Horario,
    ImportacionPersonalError,
)
from .forms import DesignacionForm, PersonaForm
from .views import _procesar_csv, gestion_legajos


class DesignacionTests(TestCase):
    def setUp(self):
        self.persona = Persona.objects.create(
            dni="30123456",
            apellido_nombre="Docente de prueba",
        )
        self.cargo = Cargo.objects.create(
            codigo="PROF",
            descripcion="Profesor",
        )

    def test_crear_designacion(self):
        designacion = Designacion.objects.create(
            persona=self.persona,
            cargo=self.cargo,
            desde=date(2026, 3, 1),
        )
        self.assertEqual(
            designacion.persona.apellido_nombre,
            "Docente de prueba",
        )

    def test_fecha_final_no_puede_ser_anterior(self):
        designacion = Designacion(
            persona=self.persona,
            cargo=self.cargo,
            desde=date(2026, 3, 10),
            hasta=date(2026, 3, 1),
        )
        with self.assertRaises(ValidationError):
            designacion.full_clean()

    def test_historial_registra_alta_cambio_y_baja(self):
        designacion = Designacion.objects.create(
            persona=self.persona,
            cargo=self.cargo,
            situacion_revista=Designacion.Situacion.INTERINO,
            desde=date(2026, 3, 1),
        )
        designacion.situacion_revista = Designacion.Situacion.TITULAR
        designacion.save()
        designacion.activo = False
        designacion.save()

        acciones = list(
            designacion.historial.order_by("pk").values_list("accion", flat=True)
        )
        self.assertEqual(
            acciones,
            [
                HistorialDesignacion.Accion.ALTA,
                HistorialDesignacion.Accion.CAMBIO_SITUACION,
                HistorialDesignacion.Accion.BAJA,
            ],
        )
        self.assertEqual(
            designacion.historial.all()[1].datos_anteriores["situacion_revista"],
            Designacion.Situacion.INTERINO,
        )

    def test_vigencia_de_designacion_respeta_rango_de_fechas(self):
        designacion = Designacion.objects.create(
            persona=self.persona,
            cargo=self.cargo,
            desde=date(2026, 3, 1),
            hasta=date(2026, 11, 30),
        )

        self.assertFalse(designacion.vigente_en(date(2026, 2, 28)))
        self.assertTrue(designacion.vigente_en(date(2026, 7, 1)))
        self.assertFalse(designacion.vigente_en(date(2026, 12, 1)))

    def test_formulario_mantiene_el_dni_inmutable_al_editar(self):
        form = PersonaForm(
            data={
                "apellido_nombre": "Apellido actualizado, Docente",
                "apellido": "Apellido actualizado",
                "nombres": "Docente",
                "sexo": "F",
                "activa": "on",
            },
            instance=self.persona,
        )

        self.assertTrue(form.is_valid(), form.errors)
        persona = form.save()
        self.assertEqual(persona.pk, "30123456")
        self.assertEqual(persona.apellido_nombre, "Apellido actualizado, Docente")

    def test_formulario_guarda_horas_semanales_por_dia(self):
        form = DesignacionForm(
            data={
                "cargo": self.cargo.pk,
                "espacio_curricular": "",
                "unidad_educativa": "",
                "situacion_revista": Designacion.Situacion.SUPLENTE,
                "anio_curso": "",
                "division_seccion": "",
                "turno": "Mañana",
                "hs_catedra": "4",
                "jornada": "",
                "especialidad": "",
                "disp_alta_nro": "",
                "sello_regional_as": "",
                "motivo": "",
                "norma_tipo": "",
                "norma_numero": "",
                "norma_anio": "",
                "organismo_emisor": "",
                "desde": "2026-03-01",
                "hasta": "",
                "pof": "",
                "anio_pof": "",
                "novedad": "",
                "observaciones": "",
                "horas_lun": "3",
                "horas_mar": "0",
                "horas_mie": "2",
                "horas_jue": "0",
                "horas_vie": "0",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.instance.persona = self.persona
        designacion = form.save()

        horas = dict(
            Horario.objects.filter(designacion=designacion).values_list(
                "dia", "horas_catedra"
            )
        )
        self.assertEqual(horas, {"LUN": 3, "MIE": 2})

    def test_csv_continua_importacion_y_registra_fila_rechazada(self):
        archivo = SimpleUploadedFile(
            "personal.csv",
            (
                "DNI,apellido_nombre,cargo_codigo,desde\n"
                "30123457,Docente válido,PROF,2026-03-01\n"
                "99999999,,PROF,2026-03-01\n"
            ).encode("utf-8"),
        )

        total, rechazadas = _procesar_csv(archivo)

        self.assertEqual(total, 2)
        self.assertEqual(rechazadas, 1)
        self.assertTrue(Persona.objects.filter(pk="30123457").exists())
        self.assertEqual(
            Designacion.objects.filter(persona_id="30123457").count(),
            1,
        )
        self.assertEqual(
            ImportacionPersonalError.objects.get().numero_fila,
            3,
        )

    def test_pantalla_renderiza_para_usuario_autenticado(self):
        usuario = get_user_model().objects.create_user(
            username="personal-test",
            password="test-password",
        )
        request = RequestFactory().get("/personal/legajos/")
        request.user = usuario

        response = gestion_legajos(request)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Legajos del personal docente",
            html=False,
        )

    def test_ruta_publica_pantalla_redirige_y_usuario_autenticado_la_ve(self):
        cliente = Client()
        url = reverse("personal:gestion_legajos")

        respuesta_anonima = cliente.get(url)
        self.assertEqual(respuesta_anonima.status_code, 302)
        self.assertIn("/accounts/login/", respuesta_anonima.url)

        usuario = get_user_model().objects.create_user(
            username="personal-route-test",
            password="test-password",
        )
        cliente.force_login(usuario)
        respuesta_autenticada = cliente.get(url)

        self.assertEqual(respuesta_autenticada.status_code, 200)
        self.assertContains(
            respuesta_autenticada,
            "Legajos del personal docente",
        )