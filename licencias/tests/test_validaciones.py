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


class ResolucionExcepcionPantallasTests(TestCase):
    """RN-08: la excepción por resolución se carga y se respeta desde las pantallas."""

    @classmethod
    def setUpTestData(cls):
        cargo = Cargo.objects.create(codigo='HC', descripcion='Hora cátedra')
        persona = Persona.objects.create(dni='99000093', apellido_nombre='Diaz, Rosa')
        cls.designacion = Designacion.objects.create(
            persona=persona, cargo=cargo, desde=date(2026, 1, 1),
        )
        cls.articulo = LicenciaArticulo.objects.create(
            cod_licencia='T-5', articulo='5', tipo_licencia='Con tope',
            categoria_informe='Duelo', sit_rev='Titular',
            goce_haberes='Con goce de haberes', autoridad='Dirección',
            plazo='Según artículo', tope_dias_anual=5,
        )
        usuario = User.objects.create_user('cargador2', password='x')
        usuario.user_permissions.set(
            Permission.objects.filter(
                content_type__app_label='licencias',
                codename__in=['add_licenciaotorgada', 'change_licenciaotorgada'],
            )
        )

    def setUp(self):
        self.client.login(username='cargador2', password='x')

    def _datos(self, **extra):
        # Lunes 02/03/2026 a viernes 13/03/2026: 10 días hábiles, más que el tope (5).
        datos = {
            'designacion': self.designacion.pk,
            'articulo': self.articulo.pk,
            'sit_rev': 'Titular',
            'desde': '2026-03-02',
            'hasta': '2026-03-13',
        }
        datos.update(extra)
        return datos

    def test_la_pantalla_de_alta_muestra_el_campo(self):
        respuesta = self.client.get('/licencias/nueva/')
        self.assertContains(respuesta, 'name="resolucion_excepcion"')

    def test_alta_que_excede_el_tope_sin_resolucion_no_se_guarda(self):
        respuesta = self.client.post('/licencias/nueva/', self._datos())
        self.assertEqual(respuesta.status_code, 200)  # vuelve al formulario con el error
        self.assertEqual(LicenciaOtorgada.objects.count(), 0)

    def test_alta_que_excede_el_tope_con_resolucion_se_guarda(self):
        respuesta = self.client.post(
            '/licencias/nueva/', self._datos(resolucion_excepcion='Res. 7/2026'),
        )
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(
            LicenciaOtorgada.objects.get().resolucion_excepcion, 'Res. 7/2026',
        )

    def test_la_pantalla_de_edicion_muestra_la_resolucion_cargada(self):
        licencia = LicenciaOtorgada.objects.create(
            designacion=self.designacion, articulo=self.articulo, sit_rev='Titular',
            desde=date(2026, 3, 2), hasta=date(2026, 3, 4),
            resolucion_excepcion='Res. 9/2026',
        )
        respuesta = self.client.get(f'/licencias/editar/{licencia.pk}/')
        self.assertContains(respuesta, 'value="Res. 9/2026"') 


class SuperposicionTests(TestCase):
    """M8: una designación no puede tener dos licencias en el mismo día."""

    @classmethod
    def setUpTestData(cls):
        cargo = Cargo.objects.create(codigo='HC', descripcion='Hora cátedra')
        persona = Persona.objects.create(dni='99000092', apellido_nombre='Sosa, Rita')
        otra = Persona.objects.create(dni='99000091', apellido_nombre='Vega, Juan')
        cls.designacion = Designacion.objects.create(
            persona=persona, cargo=cargo, desde=date(2026, 1, 1),
        )
        cls.otra_designacion = Designacion.objects.create(
            persona=otra, cargo=cargo, desde=date(2026, 1, 1),
        )
        datos = dict(
            tipo_licencia='Uno', categoria_informe='Duelo', sit_rev='Titular',
            goce_haberes='Con goce de haberes', autoridad='Dirección',
            plazo='Según artículo',
        )
        cls.articulo = LicenciaArticulo.objects.create(
            cod_licencia='S-1', articulo='1', **datos,
        )
        cls.otro_articulo = LicenciaArticulo.objects.create(
            cod_licencia='S-2', articulo='2', **datos,
        )
        # Lunes 09/03/2026 a viernes 13/03/2026.
        cls.licencia = LicenciaOtorgada.objects.create(
            designacion=cls.designacion, articulo=cls.articulo, sit_rev='Titular',
            desde=date(2026, 3, 9), hasta=date(2026, 3, 13),
        )

    def _nueva(self, desde, hasta, designacion=None):
        return LicenciaOtorgada(
            designacion=designacion or self.designacion,
            articulo=self.otro_articulo, sit_rev='Titular',
            desde=desde, hasta=hasta,
        )

    def test_licencia_que_se_pisa_con_otra_se_rechaza(self):
        nueva = self._nueva(date(2026, 3, 11), date(2026, 3, 16))
        with self.assertRaises(ValidationError) as ctx:
            nueva.full_clean()
        self.assertIn('desde', ctx.exception.message_dict)

    def test_licencia_contigua_sin_pisarse_se_acepta(self):
        self._nueva(date(2026, 3, 14), date(2026, 3, 18)).full_clean()

    def test_otra_designacion_no_se_pisa(self):
        nueva = self._nueva(
            date(2026, 3, 11), date(2026, 3, 16), designacion=self.otra_designacion,
        )
        nueva.full_clean()

    def test_la_edicion_no_se_cuenta_contra_si_misma(self):
        self.licencia.observaciones = 'Sin cambios de fechas'
        self.licencia.full_clean()

    def test_licencia_abierta_se_pisa_con_una_posterior(self):
        LicenciaOtorgada.objects.create(
            designacion=self.designacion, articulo=self.otro_articulo,
            sit_rev='Titular', desde=date(2026, 3, 20), hasta=None,
        )
        nueva = self._nueva(date(2026, 4, 1), date(2026, 4, 3))
        with self.assertRaises(ValidationError) as ctx:
            nueva.full_clean()
        self.assertIn('desde', ctx.exception.message_dict) 

class SituacionRevistaTests(TestCase):
    """M8: el artículo debe corresponder a la situación de revista de la designación."""

    @classmethod
    def setUpTestData(cls):
        cargo = Cargo.objects.create(codigo='HC', descripcion='Hora cátedra')
        luna = Persona.objects.create(dni='99000090', apellido_nombre='Luna, Ana')
        rey = Persona.objects.create(dni='99000089', apellido_nombre='Rey, Pedro')
        cls.suplente = Designacion.objects.create(
            persona=luna, cargo=cargo, desde=date(2026, 1, 1), situacion_revista='SUP',
        )
        cls.sin_situacion = Designacion.objects.create(
            persona=rey, cargo=cargo, desde=date(2026, 1, 1),
        )
        datos = dict(
            tipo_licencia='Uno', categoria_informe='Duelo',
            goce_haberes='Con goce de haberes', autoridad='Dirección',
            plazo='Según artículo',
        )
        cls.art_titular = LicenciaArticulo.objects.create(
            cod_licencia='R-1', articulo='1', sit_rev='Titular', **datos,
        )
        cls.art_suplente = LicenciaArticulo.objects.create(
            cod_licencia='R-2', articulo='2', sit_rev='Suplente', **datos,
        )

    def _licencia(self, designacion, articulo):
        return LicenciaOtorgada(
            designacion=designacion, articulo=articulo, sit_rev=articulo.sit_rev,
            desde=date(2026, 3, 9), hasta=date(2026, 3, 13),
        )

    def test_articulo_de_titular_en_designacion_de_suplente_se_rechaza(self):
        with self.assertRaises(ValidationError) as ctx:
            self._licencia(self.suplente, self.art_titular).full_clean()
        self.assertIn('articulo', ctx.exception.message_dict)

    def test_articulo_de_suplente_en_designacion_de_suplente_se_acepta(self):
        self._licencia(self.suplente, self.art_suplente).full_clean()

    def test_designacion_sin_situacion_acepta_cualquier_articulo(self):
        self._licencia(self.sin_situacion, self.art_titular).full_clean()

    def test_el_mensaje_nombra_las_dos_situaciones(self):
        with self.assertRaises(ValidationError) as ctx:
            self._licencia(self.suplente, self.art_titular).full_clean()
        mensaje = ' '.join(ctx.exception.message_dict['articulo'])
        self.assertIn('titular', mensaje)
        self.assertIn('suplente', mensaje) 

class CruceDeAnioTests(TestCase):
    """RN-08: una licencia que cruza de año se reparte entre los dos años."""

    @classmethod
    def setUpTestData(cls):
        cargo = Cargo.objects.create(codigo='HC', descripcion='Hora cátedra')
        persona = Persona.objects.create(dni=99000098, apellido_nombre='Cruce, Docente')
        cls.designacion = Designacion.objects.create(
            persona=persona, cargo=cargo, desde=date(2026, 1, 1),
        )
        cls.articulo = LicenciaArticulo.objects.create(
            cod_licencia='T-25', articulo='25', tipo_licencia='Duelo',
            categoria_informe='Duelo', sit_rev='Titular',
            goce_haberes='Con goce de haberes', autoridad='Dirección',
            plazo='Según artículo', tope_dias_anual=5,
        )

    def _licencia(self, desde, hasta):
        return LicenciaOtorgada(
            designacion=self.designacion, articulo=self.articulo, sit_rev='Titular',
            desde=desde, hasta=hasta,
        )

    def test_cruce_de_anio_se_reparte_y_cada_parte_entra_en_su_tope(self):
        # Lun 28/12/2026 a mar 05/01/2027: 4 días hábiles en 2026 y 3 en 2027.
        # Total 7 (> tope 5), pero cada año por separado entra en el tope.
        self._licencia(date(2026, 12, 28), date(2027, 1, 5)).full_clean()

    def test_cruce_de_anio_rechaza_si_se_pasa_el_tope_del_primer_anio(self):
        # Ya usó 2 días en 2026 (21 y 22/12); sumados a los 4 de diciembre = 6 > 5.
        LicenciaOtorgada.objects.create(
            designacion=self.designacion, articulo=self.articulo, sit_rev='Titular',
            desde=date(2026, 12, 21), hasta=date(2026, 12, 22),
        )
        with self.assertRaises(ValidationError) as ctx:
            self._licencia(date(2026, 12, 28), date(2027, 1, 5)).full_clean()
        self.assertIn('hasta', ctx.exception.message_dict)

    def test_cruce_de_anio_rechaza_si_se_pasa_el_tope_del_segundo_anio(self):
        # Ya usó 4 días en 2027 (11 al 14/01); sumados a los 3 de enero = 7 > 5.
        LicenciaOtorgada.objects.create(
            designacion=self.designacion, articulo=self.articulo, sit_rev='Titular',
            desde=date(2027, 1, 11), hasta=date(2027, 1, 14),
        )
        with self.assertRaises(ValidationError) as ctx:
            self._licencia(date(2026, 12, 28), date(2027, 1, 5)).full_clean()
        mensaje = ' '.join(ctx.exception.message_dict['hasta'])
        self.assertIn('2027', mensaje)  # el mensaje dice qué año se pasó 

class DesignacionDeBajaEdicionTests(TestCase):
    """N2: se puede editar una licencia cuya designación fue dada de baja."""

    @classmethod
    def setUpTestData(cls):
        cargo = Cargo.objects.create(codigo='HC', descripcion='Hora cátedra')
        persona = Persona.objects.create(dni=99000097, apellido_nombre='Baja, Docente')
        cls.designacion_baja = Designacion.objects.create(
            persona=persona, cargo=cargo, desde=date(2026, 1, 1), activo=False,
        )
        cls.articulo = LicenciaArticulo.objects.create(
            cod_licencia='T-25', articulo='25', tipo_licencia='Duelo',
            categoria_informe='Duelo', sit_rev='Titular',
            goce_haberes='Con goce de haberes', autoridad='Dirección',
            plazo='Según artículo', tope_dias_anual=5,
        )
        cls.licencia = LicenciaOtorgada.objects.create(
            designacion=cls.designacion_baja, articulo=cls.articulo, sit_rev='Titular',
            desde=date(2026, 7, 13), hasta=date(2026, 7, 14),
        )

    def test_al_editar_se_ofrece_la_designacion_dada_de_baja(self):
        from licencias.forms import LicenciaOtorgadaForm
        form = LicenciaOtorgadaForm(instance=self.licencia)
        self.assertIn(
            self.designacion_baja, form.fields['designacion'].queryset,
        )

    def test_en_un_alta_no_se_ofrecen_designaciones_dadas_de_baja(self):
        from licencias.forms import LicenciaOtorgadaForm
        form = LicenciaOtorgadaForm()
        self.assertNotIn(
            self.designacion_baja, form.fields['designacion'].queryset,
        ) 

    def test_al_editar_las_fechas_se_precargan_en_formato_iso(self):
        # El navegador solo entiende aaaa-mm-dd en un input type="date".
        from licencias.forms import LicenciaOtorgadaForm
        form = LicenciaOtorgadaForm(instance=self.licencia)
        self.assertIn('value="2026-07-13"', str(form['desde']))
        self.assertIn('value="2026-07-14"', str(form['hasta'])) 