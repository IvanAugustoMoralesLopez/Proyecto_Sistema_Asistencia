from datetime import date
from io import StringIO

from django.contrib.auth.models import Permission, User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from licencias.models import LicenciaArticulo, LicenciaOtorgada
from personal.models import Cargo, Designacion, Persona


class NroFormularioTests(TestCase):
    """RN-10: el N° de formulario se carga junto con la licencia."""

    @classmethod
    def setUpTestData(cls):
        cargo = Cargo.objects.create(codigo='HC', descripcion='Hora cátedra')
        persona = Persona.objects.create(dni='99000094', apellido_nombre='Lopez, Ana')
        cls.designacion = Designacion.objects.create(
            persona=persona, cargo=cargo, desde=date(2026, 1, 1),
        )
        cls.articulo = LicenciaArticulo.objects.create(
            cod_licencia='A-1', articulo='1', tipo_licencia='Uno',
            categoria_informe='Duelo', sit_rev='Titular',
            goce_haberes='Con goce de haberes', autoridad='Dirección',
            plazo='Según artículo',
        ) 
        usuario = User.objects.create_user('cargador', password='x')
        usuario.user_permissions.set(
            Permission.objects.filter(
                content_type__app_label='licencias',
                codename__in=['add_licenciaotorgada', 'change_licenciaotorgada'],
            )
        )

    def setUp(self):
        self.client.login(username='cargador', password='x')

    def test_el_alta_guarda_el_numero_de_formulario(self):
        respuesta = self.client.post('/licencias/nueva/', {
            'designacion': self.designacion.pk,
            'articulo': self.articulo.pk,
            'sit_rev': 'Titular',
            'desde': '2026-03-02',
            'hasta': '2026-03-04',
            'nro_formulario': 'F-1234',
        })
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(LicenciaOtorgada.objects.get().nro_formulario, 'F-1234') 

    def test_la_pantalla_de_alta_muestra_el_campo(self):
        respuesta = self.client.get('/licencias/nueva/')
        self.assertContains(respuesta, 'name="nro_formulario"')

    def test_la_pantalla_de_edicion_muestra_el_numero_cargado(self):
        licencia = LicenciaOtorgada.objects.create(
            designacion=self.designacion, articulo=self.articulo, sit_rev='Titular',
            desde=date(2026, 3, 2), hasta=date(2026, 3, 4), nro_formulario='F-9',
        )
        respuesta = self.client.get('/licencias/editar/%d/' % licencia.pk)
        self.assertContains(respuesta, 'value="F-9"') 


class EmisionUnicaTests(TestCase):
    """
    RF-16: las disposiciones se emiten desde un solo lugar, la planilla
    mensual. El generador viejo y el comando ya no numeran por su cuenta,
    para que una misma licencia no reciba dos números.
    """

    @classmethod
    def setUpTestData(cls):
        from asistencias.models import MarcaAsistencia, RegistroAsistencia

        cargo = Cargo.objects.create(codigo='HC', descripcion='Hora cátedra')
        persona = Persona.objects.create(dni='30111222', apellido_nombre='ABEL, Luis')
        designacion = Designacion.objects.create(
            persona=persona, cargo=cargo, desde=date(2026, 1, 1),
        )
        RegistroAsistencia.objects.create(
            designacion=designacion, fecha=date(2026, 10, 22),
            marca=MarcaAsistencia.objects.get(codigo='LIC'), horas_inasistidas=2,
        )
        cls.operador = User.objects.create_user(username='operador', password='x')
        cls.operador.user_permissions.add(
            Permission.objects.get(codename='change_licenciaotorgada'),
            Permission.objects.get(codename='view_licenciaotorgada'),
        )

    def test_el_comando_emite_desde_la_planilla_mensual(self):
        from licencias.planilla_mensual import procesar_mes

        procesar_mes(2026, 10)
        salida = StringIO()
        call_command('emitir_disposiciones', 2026, 10, stdout=salida)

        self.assertIn('Disp. 1/2026  ABEL, Luis', salida.getvalue())
        self.assertIn('Emitidas: 1', salida.getvalue())

    def test_el_comando_rechaza_un_mes_invalido(self):
        with self.assertRaises(CommandError):
            call_command('emitir_disposiciones', 2026, 13)

    def test_el_generador_viejo_redirige_a_la_planilla_mensual(self):
        self.client.force_login(self.operador)
        respuesta = self.client.post(
            reverse('licencias:generador_disposiciones') + '?anio=2026&mes=10'
        )
        self.assertRedirects(
            respuesta,
            reverse('licencias:planilla_mensual', args=[2026, 10]),
            fetch_redirect_response=False,
        )
        # No emitió nada por su cuenta.
        self.assertFalse(
            LicenciaOtorgada.objects.exclude(disp_numero='').exists()
        )

    def test_el_generador_viejo_sigue_pidiendo_login_y_permiso(self):
        url = reverse('licencias:generador_disposiciones')
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(User.objects.create_user(username='nadie', password='x'))
        self.assertEqual(self.client.get(url).status_code, 403)
