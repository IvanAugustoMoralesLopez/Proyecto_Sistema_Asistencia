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



class ResolucionAdjuntaTests(TestCase):
    """RF-16: se adjuntan resoluciones (PDF) a una licencia."""

    @classmethod
    def setUpTestData(cls):
        cargo = Cargo.objects.create(codigo='HC', descripcion='Hora cátedra')
        persona = Persona.objects.create(dni=99000071, apellido_nombre='Adjunto, Docente')
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

    def setUp(self):
        # Los archivos de prueba van a una carpeta temporal, no a media/.
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._override = override_settings(MEDIA_ROOT=self._tmp.name)
        self._override.enable()
        self.addCleanup(self._override.disable)

    def _resolucion(self, nombre='resolucion.pdf', contenido=b'%PDF-1.4 prueba'):
        from licencias.models import ResolucionAdjunta
        return ResolucionAdjunta(
            licencia=self.licencia,
            descripcion='Resolución ministerial N° 123/2026',
            archivo=SimpleUploadedFile(nombre, contenido),
        )

    def test_un_pdf_valido_se_acepta(self):
        self._resolucion().full_clean()

    def test_una_extension_que_no_es_pdf_se_rechaza(self):
        with self.assertRaises(ValidationError) as ctx:
            self._resolucion(nombre='resolucion.exe').full_clean()
        self.assertIn('archivo', ctx.exception.message_dict)

    def test_un_archivo_que_no_es_realmente_pdf_se_rechaza(self):
        with self.assertRaises(ValidationError) as ctx:
            self._resolucion(contenido=b'MZ esto no es un pdf').full_clean()
        self.assertIn('archivo', ctx.exception.message_dict)

    def test_un_archivo_de_mas_de_5_mb_se_rechaza(self):
        grande = b'%PDF-' + b'0' * (5 * 1024 * 1024 + 1)
        with self.assertRaises(ValidationError) as ctx:
            self._resolucion(contenido=grande).full_clean()
        self.assertIn('archivo', ctx.exception.message_dict)

    def test_se_guarda_asociada_a_la_licencia(self):
        resolucion = self._resolucion()
        resolucion.full_clean()
        resolucion.save()
        self.assertEqual(list(self.licencia.resoluciones.all()), [resolucion]) 

class ResolucionesVistasTests(TestCase):
    """RF-16: pantallas para adjuntar y descargar resoluciones."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission

        cargo = Cargo.objects.create(codigo='HC', descripcion='Hora cátedra')
        persona = Persona.objects.create(dni=99000061, apellido_nombre='Vista, Docente')
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

        User = get_user_model()
        ver = Permission.objects.get(codename='view_licenciaotorgada')
        editar = Permission.objects.get(codename='change_licenciaotorgada')
        cls.operador = User.objects.create_user(username='operador', password='x')
        cls.operador.user_permissions.add(ver, editar)
        cls.consulta = User.objects.create_user(username='consulta', password='x')
        cls.consulta.user_permissions.add(ver)
        cls.sin_permiso = User.objects.create_user(username='nadie', password='x')

    def setUp(self):
        # Los archivos de prueba van a una carpeta temporal, no a media/.
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._override = override_settings(MEDIA_ROOT=self._tmp.name)
        self._override.enable()
        self.addCleanup(self._override.disable)

        from licencias.models import ResolucionAdjunta
        self.resolucion = ResolucionAdjunta.objects.create(
            licencia=self.licencia,
            descripcion='Resolución ministerial N° 123/2026',
            archivo=SimpleUploadedFile('r.pdf', b'%PDF-1.4 prueba'),
        )

    def _url_gestion(self):
        return reverse('licencias:resoluciones_licencia', args=[self.licencia.pk])

    def _url_descarga(self):
        return reverse('licencias:descargar_resolucion', args=[self.resolucion.pk])

    def test_anonimo_es_redirigido_al_login(self):
        self.assertEqual(self.client.get(self._url_gestion()).status_code, 302)
        self.assertEqual(self.client.get(self._url_descarga()).status_code, 302)

    def test_sin_permiso_recibe_403(self):
        self.client.force_login(self.sin_permiso)
        self.assertEqual(self.client.get(self._url_gestion()).status_code, 403)
        self.assertEqual(self.client.get(self._url_descarga()).status_code, 403)

    def test_la_pantalla_lista_las_resoluciones(self):
        self.client.force_login(self.operador)
        respuesta = self.client.get(self._url_gestion())
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Resolución ministerial N° 123/2026')

    def test_se_adjunta_un_pdf(self):
        self.client.force_login(self.operador)
        respuesta = self.client.post(self._url_gestion(), {
            'descripcion': 'Resolución externa N° 9',
            'archivo': SimpleUploadedFile('otra.pdf', b'%PDF-1.4 otra'),
        })
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(self.licencia.resoluciones.count(), 2)

    def test_un_archivo_que_no_es_pdf_se_rechaza_y_no_se_guarda(self):
        self.client.force_login(self.operador)
        respuesta = self.client.post(self._url_gestion(), {
            'descripcion': 'Falsa',
            'archivo': SimpleUploadedFile('falsa.pdf', b'MZ no es un pdf'),
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'no es un PDF válido')
        self.assertEqual(self.licencia.resoluciones.count(), 1)

    def test_consulta_puede_descargar_pero_no_adjuntar(self):
        self.client.force_login(self.consulta)
        self.assertEqual(self.client.get(self._url_gestion()).status_code, 403)
        respuesta = self.client.get(self._url_descarga())
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(b''.join(respuesta.streaming_content), b'%PDF-1.4 prueba')
        self.assertIn('attachment', respuesta['Content-Disposition'])

    def test_resolucion_inexistente_devuelve_404(self):
        self.client.force_login(self.operador)
        url = reverse('licencias:descargar_resolucion', args=[999999])
        self.assertEqual(self.client.get(url).status_code, 404) 

    def test_el_listado_enlaza_a_las_resoluciones_de_cada_licencia(self):
        self.client.force_login(self.operador)
        respuesta = self.client.get(reverse('licencias:listado_licencias_otorgadas'))
        self.assertContains(respuesta, self._url_gestion()) 
