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


class EmitirDisposicionesTests(TestCase):
    """RF-16 / RN-10 / RN-11: emisión mensual de disposiciones."""

    @classmethod
    def setUpTestData(cls):
        cls.cargo = Cargo.objects.create(codigo='HC', descripcion='Hora cátedra')
        cls.articulo = LicenciaArticulo.objects.create(
            cod_licencia='A-1', articulo='1', tipo_licencia='Uno',
            categoria_informe='Duelo', sit_rev='Titular',
            goce_haberes='Con goce de haberes', autoridad='Dirección',
            plazo='Según artículo',
        )

    def _licencia(self, dni, nombre, desde, hasta, formulario='F-1', **extra):
        persona = Persona.objects.create(dni=dni, apellido_nombre=nombre)
        designacion = Designacion.objects.create(
            persona=persona, cargo=self.cargo, desde=date(2026, 1, 1),
        )
        return LicenciaOtorgada.objects.create(
            designacion=designacion, articulo=self.articulo, sit_rev='Titular',
            desde=desde, hasta=hasta, nro_formulario=formulario, **extra
        )

    def _emitir(self, anio=2026, mes=10, oficina=None):
        from licencias.services import emitir_disposiciones_mes
        return emitir_disposiciones_mes(anio, mes, oficina)

    def test_ordena_alfabeticamente_y_numera_en_forma_correlativa(self):
        zapata = self._licencia('99000001', 'Zapata, Luis', date(2026, 10, 5), date(2026, 10, 7))
        alvarez = self._licencia('99000002', 'Álvarez, Ana', date(2026, 10, 12), date(2026, 10, 13))
        benitez = self._licencia('99000003', 'Benitez, Rosa', date(2026, 10, 1), date(2026, 10, 2))
        resultado = self._emitir()
        self.assertEqual(
            [(numero, lic.pk) for numero, lic in resultado['emitidas']],
            [(1, alvarez.pk), (2, benitez.pk), (3, zapata.pk)],
        )

    def test_guarda_los_datos_de_la_disposicion(self):
        lic = self._licencia('99000001', 'Perez, Ana', date(2026, 10, 5), date(2026, 10, 7))
        self._emitir()
        lic.refresh_from_db()
        self.assertEqual(
            (lic.disp_tipo, lic.disp_oficina, lic.disp_numero, lic.disp_anio),
            ('Disposición', '1452', '1', 2026),
        )

    def test_omite_las_licencias_sin_numero_de_formulario(self):
        self._licencia('99000001', 'Perez, Ana', date(2026, 10, 5), date(2026, 10, 7))
        sin_none = self._licencia(
            '99000002', 'Gomez, Luis', date(2026, 10, 5), date(2026, 10, 7), formulario=None,
        )
        sin_vacio = self._licencia(
            '99000003', 'Ruiz, Eva', date(2026, 10, 5), date(2026, 10, 7), formulario='',
        )
        resultado = self._emitir()
        self.assertEqual(len(resultado['emitidas']), 1)
        self.assertCountEqual(
            [lic.pk for lic in resultado['omitidas']], [sin_none.pk, sin_vacio.pk],
        )
        sin_none.refresh_from_db()
        self.assertIsNone(sin_none.disp_numero)

    def test_continua_la_numeracion_de_la_oficina_y_el_anio(self):
        self._licencia(
            '99000001', 'Perez, Ana', date(2026, 10, 5), date(2026, 10, 7),
            disp_tipo='Disposición', disp_oficina='1452', disp_numero='5', disp_anio=2026,
        )
        self._licencia('99000002', 'Ruiz, Eva', date(2026, 10, 12), date(2026, 10, 13))
        resultado = self._emitir()
        self.assertEqual([numero for numero, _ in resultado['emitidas']], [6])

    def test_no_vuelve_a_numerar_lo_ya_emitido(self):
        self._licencia('99000001', 'Perez, Ana', date(2026, 10, 5), date(2026, 10, 7))
        self._emitir()
        self.assertEqual(self._emitir()['emitidas'], [])

    def test_no_incluye_licencias_de_otros_meses(self):
        self._licencia('99000001', 'Perez, Ana', date(2026, 11, 2), date(2026, 11, 4))
        self.assertEqual(self._emitir()['emitidas'], [])

    def test_mes_invalido_da_error(self):
        with self.assertRaises(ValueError):
            self._emitir(mes=13)

    def test_usa_la_oficina_de_los_parametros_del_sistema(self):
        from reportes.models import ParametroSistema
        parametros = ParametroSistema.obtener()
        parametros.codigo_oficina = '2000'
        parametros.save()
        lic = self._licencia('99000001', 'Perez, Ana', date(2026, 10, 5), date(2026, 10, 7))
        self._emitir()
        lic.refresh_from_db()
        self.assertEqual(lic.disp_oficina, '2000') 

    def test_el_comando_informa_lo_emitido_y_lo_omitido(self):
        self._licencia('99000001', 'Perez, Ana', date(2026, 10, 5), date(2026, 10, 7))
        self._licencia(
            '99000002', 'Ruiz, Eva', date(2026, 10, 5), date(2026, 10, 7), formulario=None,
        )
        salida = StringIO()
        call_command('emitir_disposiciones', 2026, 10, stdout=salida)
        texto = salida.getvalue()
        self.assertIn('Disp. 1/2026  Perez, Ana', texto)
        self.assertIn('Emitidas: 1', texto)
        self.assertIn('Omitidas por falta de N° de formulario', texto)
        self.assertIn('Ruiz, Eva', texto)

    def test_el_comando_rechaza_un_mes_invalido(self):
        with self.assertRaises(CommandError):
            call_command('emitir_disposiciones', 2026, 13)




class PrevisualizarDisposicionesTests(TestCase):
    """RF-16: la vista previa muestra qué se emitiría sin guardar nada."""

    @classmethod
    def setUpTestData(cls):
        cargo = Cargo.objects.create(codigo='HC', descripcion='Hora cátedra')
        cls.articulo = LicenciaArticulo.objects.create(
            cod_licencia='T-25', articulo='25', tipo_licencia='Duelo',
            categoria_informe='Duelo', sit_rev='Titular',
            goce_haberes='Con goce de haberes', autoridad='Dirección',
            plazo='Según artículo', tope_dias_anual=5,
        )

        def licencia(dni, apellido_nombre, formulario):
            persona = Persona.objects.create(dni=dni, apellido_nombre=apellido_nombre)
            designacion = Designacion.objects.create(
                persona=persona, cargo=cargo, desde=date(2026, 1, 1),
            )
            return LicenciaOtorgada.objects.create(
                designacion=designacion, articulo=cls.articulo, sit_rev='Titular',
                desde=date(2026, 3, 9), hasta=date(2026, 3, 9),
                nro_formulario=formulario,
            )

        # Se crean fuera de orden alfabético para comprobar el orden (RN-11).
        cls.zeta = licencia(99000081, 'ZETA, Zoe', '101')
        cls.alfa = licencia(99000082, 'ALFA, Ana', '102')
        cls.sin_formulario = licencia(99000083, 'MEDINA, Mario', '')

    def test_la_vista_previa_no_guarda_nada(self):
        from licencias.services import previsualizar_disposiciones_mes
        previsualizar_disposiciones_mes(2026, 3, oficina='1452')
        self.alfa.refresh_from_db()
        self.zeta.refresh_from_db()
        self.assertFalse(self.alfa.disp_numero)
        self.assertFalse(self.zeta.disp_numero)

    def test_la_vista_previa_numera_por_orden_alfabetico(self):
        from licencias.services import previsualizar_disposiciones_mes
        previa = previsualizar_disposiciones_mes(2026, 3, oficina='1452')
        self.assertEqual(
            [(numero, lic.pk) for numero, lic in previa['a_emitir']],
            [(1, self.alfa.pk), (2, self.zeta.pk)],
        )

    def test_la_vista_previa_lista_las_omitidas_sin_formulario(self):
        from licencias.services import previsualizar_disposiciones_mes
        previa = previsualizar_disposiciones_mes(2026, 3, oficina='1452')
        self.assertEqual([l.pk for l in previa['omitidas']], [self.sin_formulario.pk])

    def test_la_vista_previa_coincide_con_lo_que_se_emite(self):
        from licencias.services import emitir_disposiciones_mes, previsualizar_disposiciones_mes
        previa = previsualizar_disposiciones_mes(2026, 3, oficina='1452')
        emitido = emitir_disposiciones_mes(2026, 3, oficina='1452')
        self.assertEqual(
            [(n, l.pk) for n, l in previa['a_emitir']],
            [(n, l.pk) for n, l in emitido['emitidas']],
        ) 

class GeneradorDisposicionesVistaTests(TestCase):
    """RF-16: pantalla del generador de disposiciones."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission

        cargo = Cargo.objects.create(codigo='HC', descripcion='Hora cátedra')
        articulo = LicenciaArticulo.objects.create(
            cod_licencia='T-25', articulo='25', tipo_licencia='Duelo',
            categoria_informe='Duelo', sit_rev='Titular',
            goce_haberes='Con goce de haberes', autoridad='Dirección',
            plazo='Según artículo', tope_dias_anual=5,
        )

        def licencia(dni, apellido_nombre, formulario):
            persona = Persona.objects.create(dni=dni, apellido_nombre=apellido_nombre)
            designacion = Designacion.objects.create(
                persona=persona, cargo=cargo, desde=date(2026, 1, 1),
            )
            return LicenciaOtorgada.objects.create(
                designacion=designacion, articulo=articulo, sit_rev='Titular',
                desde=date(2026, 3, 9), hasta=date(2026, 3, 9),
                nro_formulario=formulario,
            )

        cls.zeta = licencia(99000091, 'ZETA, Zoe', '101')
        cls.alfa = licencia(99000092, 'ALFA, Ana', '102')
        cls.sin_formulario = licencia(99000093, 'MEDINA, Mario', '')

        User = get_user_model()
        cls.usuario = User.objects.create_user(username='emisor', password='x')
        cls.usuario.user_permissions.add(
            Permission.objects.get(codename='change_licenciaotorgada'),
        )
        cls.sin_permiso = User.objects.create_user(username='curioso', password='x')

        cls.url = reverse('licencias:generador_disposiciones')

    def test_anonimo_es_redirigido_al_login(self):
        respuesta = self.client.get(self.url, {'anio': 2026, 'mes': 3})
        self.assertEqual(respuesta.status_code, 302)

    def test_sin_permiso_recibe_403(self):
        self.client.force_login(self.sin_permiso)
        respuesta = self.client.get(self.url, {'anio': 2026, 'mes': 3})
        self.assertEqual(respuesta.status_code, 403)

    def test_get_muestra_la_vista_previa_sin_emitir(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.get(self.url, {'anio': 2026, 'mes': 3})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'ALFA, Ana')
        self.assertContains(respuesta, 'ZETA, Zoe')
        self.assertContains(respuesta, 'MEDINA, Mario')  # omitida
        self.alfa.refresh_from_db()
        self.assertFalse(self.alfa.disp_numero)

    def test_post_emite_las_disposiciones_y_redirige(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.post(self.url, {'anio': 2026, 'mes': 3})
        self.assertEqual(respuesta.status_code, 302)
        self.alfa.refresh_from_db()
        self.zeta.refresh_from_db()
        self.sin_formulario.refresh_from_db()
        self.assertEqual(self.alfa.disp_numero, '1')
        self.assertEqual(self.zeta.disp_numero, '2')
        self.assertFalse(self.sin_formulario.disp_numero)

    def test_mes_fuera_de_rango_devuelve_404(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.get(self.url, {'anio': 2026, 'mes': 13})
        self.assertEqual(respuesta.status_code, 404) 
