from datetime import date

from django.test import TestCase
from django.urls import reverse

from licencias.models import LicenciaArticulo, LicenciaOtorgada
from personal.models import Cargo, Designacion, Persona


class MarcadoDeAsistenciasAlGuardarTests(TestCase):
    """RN-07 / RF-14: guardar una licencia marca sus dias en asistencias."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        from personal.models import Horario

        cargo = Cargo.objects.create(codigo='HC', descripcion='Hora cátedra')
        persona = Persona.objects.create(
            dni='99000051', apellido_nombre='Marcada, Docente',
        )
        cls.designacion = Designacion.objects.create(
            persona=persona, cargo=cargo, desde=date(2026, 1, 1),
            situacion_revista='TIT',
        )
        for dia in ('LUN', 'MAR', 'MIE', 'JUE', 'VIE'):
            Horario.objects.create(
                designacion=cls.designacion, dia=dia, horas_catedra=2,
            )
        cls.articulo = LicenciaArticulo.objects.create(
            cod_licencia='T-14', articulo='14', tipo_licencia='Enfermedad común',
            categoria_informe='Enfermedad común', sit_rev='Titular',
            goce_haberes='Con goce de haberes', autoridad='Dirección',
            plazo='Según artículo', tope_dias_anual=30,
        )
        cls.operador = get_user_model().objects.create_user(
            username='marcador', password='x',
        )
        cls.operador.user_permissions.add(
            Permission.objects.get(codename='add_licenciaotorgada'),
            Permission.objects.get(codename='change_licenciaotorgada'),
            Permission.objects.get(codename='view_licenciaotorgada'),
        )

    def _datos_alta(self, **cambios):
        # Lunes 9 a viernes 13 de marzo de 2026.
        datos = {
            'designacion': self.designacion.pk,
            'articulo': self.articulo.pk,
            'sit_rev': 'Titular',
            'desde': '2026-03-09',
            'hasta': '2026-03-13',
            'disp_tipo': 'Disposición',
            'disp_oficina': '1452',
            'disp_numero': '12',
            'disp_anio': '2026',
            'sello_regional_as': '',
            'justifica': '',
            'nro_formulario': '',
            'resolucion_excepcion': '',
            'observaciones': '',
        }
        datos.update(cambios)
        return datos

    def _guardar_alta(self):
        self.client.force_login(self.operador)
        respuesta = self.client.post(
            reverse('licencias:nueva_licencia_otorgada'), self._datos_alta(),
        )
        errores = respuesta.context['form'].errors if respuesta.context else ''
        self.assertEqual(respuesta.status_code, 302, errores)
        return respuesta

    def test_el_alta_marca_los_dias_en_asistencias(self):
        from asistencias.models import RegistroAsistencia

        self._guardar_alta()

        registros = RegistroAsistencia.objects.filter(
            designacion=self.designacion,
        )
        self.assertEqual(registros.count(), 5)
        self.assertEqual(
            set(registros.values_list('marca__codigo', flat=True)), {'LIC'},
        )
        licencia = LicenciaOtorgada.objects.get(designacion=self.designacion)
        self.assertEqual(
            set(registros.values_list('licencia_id', flat=True)),
            {licencia.pk},
        )

    def test_el_alta_informa_cuantos_dias_se_marcaron(self):
        from django.contrib.messages import get_messages

        respuesta = self._guardar_alta()

        textos = [str(m) for m in get_messages(respuesta.wsgi_request)]
        self.assertIn('Se marcaron 5 días en asistencias.', textos) 

    def test_la_edicion_marca_los_dias_nuevos_sin_duplicar(self):
        from asistencias.models import RegistroAsistencia
        from django.contrib.messages import get_messages

        self.client.force_login(self.operador)
        self.client.post(
            reverse('licencias:nueva_licencia_otorgada'),
            self._datos_alta(hasta='2026-03-11'),
        )
        licencia = LicenciaOtorgada.objects.get(designacion=self.designacion)
        registros = RegistroAsistencia.objects.filter(
            designacion=self.designacion,
        )
        self.assertEqual(registros.count(), 3)

        respuesta = self.client.post(
            reverse('licencias:editar_licencia_otorgada', args=[licencia.pk]),
            self._datos_alta(hasta='2026-03-13'),
        )

        errores = respuesta.context['form'].errors if respuesta.context else ''
        self.assertEqual(respuesta.status_code, 302, errores)
        self.assertEqual(registros.count(), 5)
        textos = [str(m) for m in get_messages(respuesta.wsgi_request)]
        self.assertIn('Se marcaron 5 días en asistencias.', textos) 

    def test_la_edicion_avisa_de_los_dias_que_quedaron_marcados_de_mas(self):
        from django.contrib.messages import get_messages

        self.client.force_login(self.operador)
        self.client.post(
            reverse('licencias:nueva_licencia_otorgada'), self._datos_alta(),
        )
        licencia = LicenciaOtorgada.objects.get(designacion=self.designacion)

        # Se acorta la licencia: el jueves 12 y el viernes 13 quedan de mas.
        respuesta = self.client.post(
            reverse('licencias:editar_licencia_otorgada', args=[licencia.pk]),
            self._datos_alta(hasta='2026-03-11'),
        )

        errores = respuesta.context['form'].errors if respuesta.context else ''
        self.assertEqual(respuesta.status_code, 302, errores)
        textos = [str(m) for m in get_messages(respuesta.wsgi_request)]
        avisos = [t for t in textos if '12/03/2026' in t and '13/03/2026' in t]
        self.assertTrue(avisos, textos)