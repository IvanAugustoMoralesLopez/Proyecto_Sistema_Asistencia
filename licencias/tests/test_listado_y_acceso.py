from datetime import date
from unittest import mock

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError

from django.contrib.auth.models import Permission, User

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase 

from django.urls import reverse

from personal.models import (
    Carrera,
    Cargo,
    Designacion,
    EspacioCurricular,
    Horario,
    Persona,
)

from licencias.clasificacion import (
    CATEGORIAS_POR_PLANILLA,
    CategoriaSinPlanillaError,
    PLANILLA_IL01,
    PLANILLA_IL02,
    planilla_para_categoria,
)
from licencias.dias import contar_dias_habiles, listar_dias_habiles, mes_vecino, rango_en_anio
from licencias.models import LicenciaArticulo, LicenciaOtorgada
from licencias.services import dias_usados_en_anio 
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings 

class ListadoFiltrosTests(TestCase):
    """M4: un filtro inválido en la URL no debe romper el listado."""

    @classmethod
    def setUpTestData(cls):
        cargo = Cargo.objects.create(codigo='HC', descripcion='Hora cátedra')
        persona = Persona.objects.create(dni=99000098, apellido_nombre='Gomez, Ana')
        otra = Persona.objects.create(dni=99000097, apellido_nombre='Ruiz, Luis')
        d1 = Designacion.objects.create(persona=persona, cargo=cargo, desde=date(2026, 1, 1))
        d2 = Designacion.objects.create(persona=otra, cargo=cargo, desde=date(2026, 1, 1))
        cls.art1 = LicenciaArticulo.objects.create(
            cod_licencia='A-1', articulo='1', tipo_licencia='Uno',
            categoria_informe='Duelo', sit_rev='Titular',
            goce_haberes='Con goce de haberes', autoridad='Dirección',
            plazo='Según artículo',
        )
        cls.art2 = LicenciaArticulo.objects.create(
            cod_licencia='A-2', articulo='2', tipo_licencia='Dos',
            categoria_informe='Duelo', sit_rev='Titular',
            goce_haberes='Con goce de haberes', autoridad='Dirección',
            plazo='Según artículo',
        )
        LicenciaOtorgada.objects.create(
            designacion=d1, articulo=cls.art1, sit_rev='Titular',
            desde=date(2026, 3, 2), hasta=date(2026, 3, 4),
        )
        LicenciaOtorgada.objects.create(
            designacion=d2, articulo=cls.art2, sit_rev='Titular',
            desde=date(2026, 6, 1), hasta=date(2026, 6, 3),
        )
        usuario = User.objects.create_user('lector', password='x')
        usuario.user_permissions.add(
            Permission.objects.get(
                content_type__app_label='licencias', codename='view_licenciaotorgada',
            )
        )

    def setUp(self):
        self.client.login(username='lector', password='x')

    def _cantidad(self, parametros=''):
        respuesta = self.client.get('/licencias/listado/' + parametros)
        self.assertEqual(respuesta.status_code, 200)
        return len(respuesta.context['licencias'])

    def test_sin_filtros_muestra_todas(self):
        self.assertEqual(self._cantidad(), 2)

    def test_filtros_invalidos_no_rompen_y_se_ignoran(self):
        for parametros in ('?articulo=abc', '?fecha_desde=xx', '?fecha_hasta=xx'):
            with self.subTest(parametros=parametros):
                self.assertEqual(self._cantidad(parametros), 2)

    def test_filtros_invalidos_muestran_aviso(self):
        respuesta = self.client.get('/licencias/listado/?articulo=abc', follow=True)
        self.assertContains(respuesta, 'ignoraron')

    def test_filtro_por_articulo(self):
        self.assertEqual(self._cantidad('?articulo=%d' % self.art1.pk), 1)

    def test_filtro_por_docente(self):
        self.assertEqual(self._cantidad('?docente=gomez'), 1)
        self.assertEqual(self._cantidad('?docente=nadie'), 0)

    def test_filtro_por_fechas(self):
        self.assertEqual(self._cantidad('?fecha_desde=2026-05-01'), 1)
        self.assertEqual(self._cantidad('?fecha_hasta=2026-04-01'), 1) 




class AccesoALasVistasTests(TestCase):
    """A4: un anónimo va al login; un usuario sin permiso recibe 403."""

    URLS = (
        '/licencias/listado/',
        '/licencias/nueva/',
        '/licencias/editar/1/',
        '/licencias/reporte/2026/10/',
    )

    @classmethod
    def setUpTestData(cls):
        User.objects.create_user('sinpermisos', password='x')

    def test_anonimo_es_redirigido_al_login(self):
        for url in self.URLS:
            with self.subTest(url=url):
                respuesta = self.client.get(url)
                self.assertEqual(respuesta.status_code, 302)
                self.assertTrue(respuesta.url.startswith('/accounts/login/'))

    def test_usuario_sin_permiso_recibe_403(self):
        self.client.login(username='sinpermisos', password='x')
        for url in self.URLS:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)  


class EncabezadosPantallasTests(TestCase):
    """Las pantallas nuevas llevan la ruta y el título, como las demás."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission

        cargo = Cargo.objects.create(codigo='HC', descripcion='Hora cátedra')
        persona = Persona.objects.create(dni=99000051, apellido_nombre='Encabezado, Docente')
        designacion = Designacion.objects.create(
            persona=persona, cargo=cargo, desde=date(2026, 1, 1),
        )
        articulo = LicenciaArticulo.objects.create(
            cod_licencia='T-25', articulo='25', tipo_licencia='Duelo',
            categoria_informe='Duelo', sit_rev='Titular',
            goce_haberes='Con goce de haberes', autoridad='Dirección',
            plazo='Según artículo', tope_dias_anual=5,
        )
        cls.licencia = LicenciaOtorgada.objects.create(
            designacion=designacion, articulo=articulo, sit_rev='Titular',
            desde=date(2026, 3, 9), hasta=date(2026, 3, 9),
        )
        cls.operador = get_user_model().objects.create_user(username='cabecera', password='x')
        cls.operador.user_permissions.add(
            Permission.objects.get(codename='change_licenciaotorgada'),
        )

    def test_el_generador_muestra_la_ruta_y_el_titulo(self):
        self.client.force_login(self.operador)
        respuesta = self.client.get(
            reverse('licencias:generador_disposiciones'), {'anio': 2026, 'mes': 3},
        )
        self.assertContains(respuesta, 'Administración / Licencias / Generador de disposiciones')
        self.assertContains(respuesta, '<h1 class="h3 mb-1">Generador de disposiciones</h1>', html=True)

    def test_resoluciones_muestra_la_ruta_y_el_titulo(self):
        self.client.force_login(self.operador)
        respuesta = self.client.get(
            reverse('licencias:resoluciones_licencia', args=[self.licencia.pk]),
        )
        self.assertContains(respuesta, 'Administración / Licencias / Resoluciones')
        self.assertContains(respuesta, '<h1 class="h3 mb-1">Resoluciones de la licencia</h1>', html=True) 
