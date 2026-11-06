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






class TopeAnualEdicionTests(TestCase):
    """RN-08: el tope anual también se valida al editar una licencia."""

    @classmethod
    def setUpTestData(cls):
        cargo = Cargo.objects.create(codigo='HC', descripcion='Hora cátedra')
        persona = Persona.objects.create(dni=99000099, apellido_nombre='Prueba, Docente')
        cls.designacion = Designacion.objects.create(
            persona=persona, cargo=cargo, desde=date(2026, 1, 1),
        )
        cls.articulo = LicenciaArticulo.objects.create(
            cod_licencia='T-25', articulo='25', tipo_licencia='Duelo',
            categoria_informe='Duelo', sit_rev='Titular',
            goce_haberes='Con goce de haberes', autoridad='Dirección',
            plazo='Según artículo', tope_dias_anual=5,
        )
        # Lunes 13/07/2026 a viernes 17/07/2026: 5 días hábiles (justo el tope).
        cls.licencia = LicenciaOtorgada.objects.create(
            designacion=cls.designacion, articulo=cls.articulo, sit_rev='Titular',
            desde=date(2026, 7, 13), hasta=date(2026, 7, 17),
        )

    def test_dias_usados_cuenta_todas_las_licencias(self):
        self.assertEqual(dias_usados_en_anio('99000099', '25', 2026), 5)

    def test_dias_usados_puede_excluir_una_licencia(self):
        self.assertEqual(
            dias_usados_en_anio('99000099', '25', 2026, excluir_id=self.licencia.pk), 0,
        )

    def test_alta_que_supera_el_tope_se_rechaza(self):
        nueva = LicenciaOtorgada(
            designacion=self.designacion, articulo=self.articulo, sit_rev='Titular',
            desde=date(2026, 7, 20), hasta=date(2026, 7, 20),
        )
        with self.assertRaises(ValidationError) as ctx:
            nueva.full_clean()
        self.assertIn('hasta', ctx.exception.message_dict)

    def test_edicion_que_supera_el_tope_se_rechaza(self):
        self.licencia.hasta = date(2026, 7, 24)  # 10 días hábiles
        with self.assertRaises(ValidationError) as ctx:
            self.licencia.full_clean()
        self.assertIn('hasta', ctx.exception.message_dict)


    def test_edicion_dentro_del_tope_se_acepta(self):
        self.licencia.observaciones = 'Duelo familiar'
        self.licencia.full_clean()  # no debe lanzar ValidationError  

    def test_edicion_dentro_del_tope_se_acepta(self):
        self.licencia.observaciones = 'Duelo familiar'
        self.licencia.full_clean()  # no debe lanzar ValidationError

    def test_alta_que_supera_el_tope_con_resolucion_se_acepta(self):
        nueva = LicenciaOtorgada(
            designacion=self.designacion, articulo=self.articulo, sit_rev='Titular',
            desde=date(2026, 7, 20), hasta=date(2026, 7, 20),
            resolucion_excepcion='Res. 123/2026',
        )
        nueva.full_clean()  # la resolución de excepción habilita pasar el tope

    def test_alta_que_supera_el_tope_con_resolucion_en_blanco_se_rechaza(self):
        nueva = LicenciaOtorgada(
            designacion=self.designacion, articulo=self.articulo, sit_rev='Titular',
            desde=date(2026, 7, 20), hasta=date(2026, 7, 20),
            resolucion_excepcion='   ',
        )
        with self.assertRaises(ValidationError) as ctx:
            nueva.full_clean()
        self.assertIn('hasta', ctx.exception.message_dict)

    def test_edicion_que_supera_el_tope_con_resolucion_se_acepta(self):
        self.licencia.hasta = date(2026, 7, 24)  # 10 días hábiles
        self.licencia.resolucion_excepcion = 'Res. 123/2026'
        self.licencia.full_clean()  # no debe lanzar ValidationError 


    def test_el_mensaje_de_tope_nombra_el_articulo_y_la_situacion_de_revista(self):
        nueva = LicenciaOtorgada(
            designacion=self.designacion, articulo=self.articulo, sit_rev='Titular',
            desde=date(2026, 7, 20), hasta=date(2026, 7, 20),
        )
        with self.assertRaises(ValidationError) as ctx:
            nueva.full_clean()
        mensaje = ' '.join(ctx.exception.message_dict['hasta'])
        self.assertIn('artículo 25', mensaje)
        self.assertIn('Estatuto Docente de la provincia del Chaco', mensaje)
        self.assertIn('personal titular', mensaje)
        self.assertIn('5 días', mensaje)


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


class FechasInvertidasTests(TestCase):
    """N4: Hasta anterior a Desde da un único error, sin un error de tope engañoso."""

    @classmethod
    def setUpTestData(cls):
        cargo = Cargo.objects.create(codigo='HC', descripcion='Hora cátedra')
        persona = Persona.objects.create(dni=99000096, apellido_nombre='Diaz, Eva')
        cls.designacion = Designacion.objects.create(
            persona=persona, cargo=cargo, desde=date(2026, 1, 1),
        )
        cls.articulo = LicenciaArticulo.objects.create(
            cod_licencia='A-3', articulo='3', tipo_licencia='Tres',
            categoria_informe='Duelo', sit_rev='Titular',
            goce_haberes='Con goce de haberes', autoridad='Dirección',
            plazo='Según artículo', tope_dias_anual=5,
        )
        usuario = User.objects.create_user('cargador', password='x')
        usuario.user_permissions.add(
            Permission.objects.get(
                content_type__app_label='licencias', codename='add_licenciaotorgada',
            )
        )

    def setUp(self):
        self.client.login(username='cargador', password='x')

    def test_hasta_anterior_a_desde_da_un_solo_error(self):
        respuesta = self.client.post('/licencias/nueva/', {
            'designacion': self.designacion.pk,
            'articulo': self.articulo.pk,
            'sit_rev': 'Titular',
            'desde': '2026-10-20',
            'hasta': '2026-10-10',
            'justifica': '',
        })
        self.assertEqual(respuesta.status_code, 200)
        errores = respuesta.context['form'].errors['hasta']
        self.assertEqual(len(errores), 1)
        self.assertIn('anterior', errores[0])
        self.assertEqual(LicenciaOtorgada.objects.count(), 0)

    def test_hasta_anterior_a_desde_se_rechaza_en_el_modelo(self):
        licencia = LicenciaOtorgada(
            designacion=self.designacion, articulo=self.articulo, sit_rev='Titular',
            desde=date(2026, 10, 20), hasta=date(2026, 10, 10),
        )
        with self.assertRaises(ValidationError) as ctx:
            licencia.full_clean()
        self.assertIn('hasta', ctx.exception.message_dict) 

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

class ReporteMensualTests(TestCase):
    """RF-12/RF-13: el reporte muestra nombres y calcula las horas afectadas."""

    @classmethod
    def setUpTestData(cls):
        cargo = Cargo.objects.create(codigo='HC', descripcion='Hora cátedra')
        carrera = Carrera.objects.create(nombre='Tecnicatura de prueba')
        materia = EspacioCurricular.objects.create(nombre='Matematica I', carrera=carrera)
        perez = Persona.objects.create(dni='99000096', apellido_nombre='Perez, Marta')
        ruiz = Persona.objects.create(dni='99000095', apellido_nombre='Ruiz, Luis')
        d_perez = Designacion.objects.create(
            persona=perez, cargo=cargo, espacio_curricular=materia,
            desde=date(2026, 1, 1),
        )
        d_ruiz = Designacion.objects.create(
            persona=ruiz, cargo=cargo, desde=date(2026, 1, 1),
        )
        # Perez tiene 4 horas cátedra los lunes.
        Horario.objects.create(designacion=d_perez, dia='LUN', horas_catedra=4)
        articulo = LicenciaArticulo.objects.create(
            cod_licencia='A-1', articulo='1', tipo_licencia='Uno',
            categoria_informe='Duelo', sit_rev='Titular',
            goce_haberes='Con goce de haberes', autoridad='Dirección',
            plazo='Según artículo',
        )
        # Lunes 05/10/2026 a viernes 09/10/2026: 5 días, un solo lunes.
        LicenciaOtorgada.objects.create(
            designacion=d_perez, articulo=articulo, sit_rev='Titular',
            desde=date(2026, 10, 5), hasta=date(2026, 10, 9),
        )
        # Licencia de otro mes: no debe aparecer en el reporte de octubre.
        LicenciaOtorgada.objects.create(
            designacion=d_ruiz, articulo=articulo, sit_rev='Titular',
            desde=date(2026, 3, 2), hasta=date(2026, 3, 4),
        )
        usuario = User.objects.create_user('lector', password='x')
        usuario.user_permissions.add(
            Permission.objects.get(
                content_type__app_label='licencias', codename='view_licenciaotorgada',
            )
        )

    def setUp(self):
        self.client.login(username='lector', password='x')

    def test_muestra_nombre_del_docente_y_de_la_materia(self):
        respuesta = self.client.get('/licencias/reporte/2026/10/')
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Perez, Marta')
        self.assertContains(respuesta, 'Matematica I')

    def test_no_incluye_licencias_de_otros_meses(self):
        respuesta = self.client.get('/licencias/reporte/2026/10/')
        self.assertNotContains(respuesta, 'Ruiz, Luis')

    def test_calcula_dias_y_horas_afectadas(self):
        respuesta = self.client.get('/licencias/reporte/2026/10/')
        desglose = respuesta.context['desglose']
        self.assertEqual(len(desglose), 1)
        self.assertEqual(desglose[0]['dias_totales'], 5)
        self.assertEqual(desglose[0]['horas_descontadas'], 4) 

    def test_calcula_el_total_de_horas_del_mes(self):
        respuesta = self.client.get('/licencias/reporte/2026/10/')
        self.assertEqual(respuesta.context['total_horas'], 4) 

    def test_cada_fila_incluye_el_cargo_de_la_designacion(self):
        respuesta = self.client.get('/licencias/reporte/2026/10/')
        self.assertEqual(respuesta.context['desglose'][0]['cargo'], 'Hora cátedra')

    def test_la_tabla_muestra_la_columna_cargo(self):
        respuesta = self.client.get('/licencias/reporte/2026/10/')
        self.assertContains(respuesta, '<th>Cargo</th>')
        self.assertContains(respuesta, 'Hora cátedra')    

    def test_mes_sin_licencias_tiene_total_cero(self):
        respuesta = self.client.get('/licencias/reporte/2026/11/')
        self.assertEqual(respuesta.context['total_horas'], 0) 

    def test_navegacion_de_enero_vuelve_a_diciembre(self):
        respuesta = self.client.get('/licencias/reporte/2026/1/')
        self.assertEqual(respuesta.context['mes_anterior'], {'anio': 2025, 'mes': 12})
        self.assertEqual(respuesta.context['mes_siguiente'], {'anio': 2026, 'mes': 2})

    def test_navegacion_de_diciembre_pasa_al_anio_siguiente(self):
        respuesta = self.client.get('/licencias/reporte/2026/12/')
        self.assertEqual(respuesta.context['mes_anterior'], {'anio': 2026, 'mes': 11})
        self.assertEqual(respuesta.context['mes_siguiente'], {'anio': 2027, 'mes': 1})

    def test_agrupa_por_planilla_y_los_subtotales_suman_el_total(self):
        respuesta = self.client.get('/licencias/reporte/2026/10/')
        grupos = respuesta.context['grupos']
        self.assertEqual(
            [g['planilla'] for g in grupos],
            ['IL-01', 'IL-02', 'SIN CLASIFICAR'],
        )
        self.assertEqual(sum(len(g['filas']) for g in grupos), 1)
        self.assertEqual(
            sum(g['total_horas'] for g in grupos),
            respuesta.context['total_horas'],
        )
        for grupo in grupos:
            for fila in grupo['filas']:
                self.assertEqual(fila['planilla'], grupo['planilla'])

    def test_los_botones_apuntan_a_los_meses_vecinos(self):
        respuesta = self.client.get('/licencias/reporte/2026/10/')
        self.assertContains(respuesta, '/licencias/reporte/2026/9/')
        self.assertContains(respuesta, '/licencias/reporte/2026/11/')

    def test_los_titulos_muestran_salud_y_administrativas_con_su_planilla(self):
        respuesta = self.client.get('/licencias/reporte/2026/10/')
        self.assertContains(respuesta, 'Licencias por salud (planilla IL-01)')
        self.assertContains(respuesta, 'Licencias administrativas (planilla IL-02)')
        # El código ya no encabeza el título.
        self.assertNotContains(respuesta, 'IL-01: licencias por salud')
        self.assertNotContains(respuesta, 'IL-02: razones particulares')

    def test_mes_invalido_da_404(self):
        respuesta = self.client.get('/licencias/reporte/2026/13/')
        self.assertEqual(respuesta.status_code, 404) 

    def test_anio_fuera_de_rango_da_404(self):
        self.assertEqual(self.client.get('/licencias/reporte/0/5/').status_code, 404)
        self.assertEqual(self.client.get('/licencias/reporte/3000/5/').status_code, 404)    


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

class FechaDeHoyTests(TestCase):
    """B4/B8: "hoy" sale de un solo lugar, con la zona horaria del proyecto."""

    @classmethod
    def setUpTestData(cls):
        cargo = Cargo.objects.create(codigo='HC', descripcion='Hora cátedra')
        persona = Persona.objects.create(dni=99000041, apellido_nombre='Hoy, Docente')
        designacion = Designacion.objects.create(
            persona=persona, cargo=cargo, desde=date(2026, 1, 1),
        )
        articulo = LicenciaArticulo.objects.create(
            cod_licencia='T-25', articulo='25', tipo_licencia='Duelo',
            categoria_informe='Duelo', sit_rev='Titular',
            goce_haberes='Con goce de haberes', autoridad='Dirección',
            plazo='Según artículo', tope_dias_anual=50,
        )
        # Licencia abierta (sin fecha de fin): cuenta hasta "hoy".
        LicenciaOtorgada.objects.create(
            designacion=designacion, articulo=articulo, sit_rev='Titular',
            desde=date(2026, 3, 2),
        )

    def test_fecha_de_hoy_usa_la_fecha_local_del_proyecto(self):
        from licencias.dias import fecha_de_hoy
        with mock.patch('django.utils.timezone.localdate', return_value=date(2026, 3, 6)):
            self.assertEqual(fecha_de_hoy(), date(2026, 3, 6))

    def test_una_licencia_abierta_cuenta_hasta_la_fecha_de_hoy(self):
        # Lunes 02/03 a viernes 06/03/2026: 5 días hábiles.
        with mock.patch('django.utils.timezone.localdate', return_value=date(2026, 3, 6)):
            self.assertEqual(dias_usados_en_anio('99000041', '25', 2026), 5) 

class AsistenteDeImputacionServicioTests(TestCase):
    """RF-15: datos del catálogo para guiar la elección del artículo."""

    @classmethod
    def setUpTestData(cls):
        def articulo(cod, numero, tipo, categoria, sit_rev, tope):
            return LicenciaArticulo.objects.create(
                cod_licencia=cod, articulo=numero, tipo_licencia=tipo,
                categoria_informe=categoria, sit_rev=sit_rev,
                goce_haberes='Con goce de haberes', autoridad='Dirección',
                plazo='Según artículo', tope_dias_anual=tope,
            )

        cls.salud = articulo('T-14', '14', 'Enfermedad común', 'Enfermedad común', 'Titular', 30)
        cls.duelo = articulo('T-25', '25', 'Duelo', 'Duelo', 'Titular', 5)
        cls.suplente = articulo('S-31', '31', 'Enfermedad común', 'Enfermedad común', 'Suplente', 20)
        cls.rara = articulo('T-99', '99', 'Rara', 'Categoría inventada', 'Titular', 10)

    def _por_id(self, situacion=None):
        from licencias.services import articulos_para_asistente
        return {dato['id']: dato for dato in articulos_para_asistente(situacion)}

    def test_cada_articulo_trae_su_planilla_y_sus_datos(self):
        datos = self._por_id()
        salud = datos[self.salud.pk]
        self.assertEqual(salud['planilla'], 'IL-01')
        self.assertEqual(salud['planilla_titulo'], 'IL-01 Salud')
        self.assertEqual(salud['tope_dias_anual'], 30)
        self.assertEqual(salud['goce_haberes'], 'Con goce de haberes')
        self.assertEqual(salud['situacion'], 'titular')
        duelo = datos[self.duelo.pk]
        self.assertEqual(duelo['planilla'], 'IL-02')
        self.assertEqual(duelo['planilla_titulo'], 'IL-02 Administrativas')

    def test_una_categoria_sin_planilla_no_rompe_la_pagina(self):
        rara = self._por_id()[self.rara.pk]
        self.assertIsNone(rara['planilla'])
        self.assertEqual(rara['planilla_titulo'], 'Sin planilla asignada')

    def test_se_filtra_por_situacion_de_revista(self):
        self.assertEqual(list(self._por_id('Suplente')), [self.suplente.pk])
        self.assertEqual(list(self._por_id('suplente')), [self.suplente.pk])

    def test_sin_filtro_devuelve_todo_el_catalogo(self):
        self.assertEqual(len(self._por_id()), 4) 

class AsistenteDeImputacionPantallaTests(TestCase):
    """RF-15: las pantallas de alta y edición llevan los datos para guiar."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission

        cargo = Cargo.objects.create(codigo='HC', descripcion='Hora cátedra')
        persona = Persona.objects.create(dni=99000031, apellido_nombre='Guiada, Docente')
        cls.designacion = Designacion.objects.create(
            persona=persona, cargo=cargo, desde=date(2026, 1, 1),
            situacion_revista='INT',
        )
        articulo = LicenciaArticulo.objects.create(
            cod_licencia='T-25', articulo='25', tipo_licencia='Duelo',
            categoria_informe='Duelo', sit_rev='Titular',
            goce_haberes='Con goce de haberes', autoridad='Dirección',
            plazo='Según artículo', tope_dias_anual=5,
        )
        cls.licencia = LicenciaOtorgada.objects.create(
            designacion=cls.designacion, articulo=articulo, sit_rev='Titular',
            desde=date(2026, 3, 9), hasta=date(2026, 3, 9),
        )
        cls.operador = get_user_model().objects.create_user(username='guia', password='x')
        cls.operador.user_permissions.add(
            Permission.objects.get(codename='add_licenciaotorgada'),
            Permission.objects.get(codename='change_licenciaotorgada'),
            Permission.objects.get(codename='view_licenciaotorgada'),
        )

    def test_cada_designacion_lleva_su_situacion_de_revista(self):
        from licencias.forms import LicenciaOtorgadaForm
        html = str(LicenciaOtorgadaForm()['designacion'])
        self.assertIn('data-situacion="interino"', html)

    def test_el_alta_lleva_los_datos_del_catalogo(self):
        self.client.force_login(self.operador)
        respuesta = self.client.get(reverse('licencias:nueva_licencia_otorgada'))
        self.assertContains(respuesta, 'id="datos-articulos"')
        self.assertContains(respuesta, 'IL-02 Administrativas')

    def test_la_edicion_lleva_los_datos_del_catalogo(self):
        self.client.force_login(self.operador)
        respuesta = self.client.get(
            reverse('licencias:editar_licencia_otorgada', args=[self.licencia.pk]),
        )
        self.assertContains(respuesta, 'id="datos-articulos"')
        self.assertContains(respuesta, 'IL-02 Administrativas')

    def test_la_edicion_no_muestra_marcas_de_codigo_sobrantes(self):
        self.client.force_login(self.operador)
        respuesta = self.client.get(
            reverse('licencias:editar_licencia_otorgada', args=[self.licencia.pk]),
        )
        self.assertNotContains(respuesta, '```')

    def test_cancelar_del_alta_vuelve_al_listado_real(self):
        import re
        self.client.force_login(self.operador)
        respuesta = self.client.get(reverse('licencias:nueva_licencia_otorgada'))
        # Se busca el enlace "Cancelar" en particular, porque el menú de la
        # página puede tener otros enlaces al listado o a la maqueta.
        enlace = re.search(
            r'<a[^>]*href="([^"]+)"[^>]*>\s*Cancelar\s*</a>',
            respuesta.content.decode(),
        )
        self.assertIsNotNone(enlace, 'No se encontró el botón Cancelar')
        self.assertEqual(
            enlace.group(1),
            reverse('licencias:listado_licencias_otorgadas'),
        ) 

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

class ReporteMensualInasistenciasTests(TestCase):
    """RF-12: el reporte mensual incluye las inasistencias del registro."""

    @classmethod
    def setUpTestData(cls):
        from decimal import Decimal
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        from asistencias.models import MarcaAsistencia, RegistroAsistencia
        from personal.models import Carrera, EspacioCurricular

        cargo = Cargo.objects.create(codigo='HC', descripcion='Hora cátedra')
        carrera = Carrera.objects.create(nombre='Profesorado de Matemática')
        espacio = EspacioCurricular.objects.create(
            nombre='Álgebra', carrera=carrera,
        )
        persona = Persona.objects.create(
            dni='99000071', apellido_nombre='Faltadora, Docente',
        )
        designacion = Designacion.objects.create(
            persona=persona, cargo=cargo, espacio_curricular=espacio,
            desde=date(2026, 1, 1), situacion_revista='TIT',
        )

        def registrar(fecha, codigo, horas):
            RegistroAsistencia.objects.create(
                designacion=designacion, fecha=fecha,
                marca=MarcaAsistencia.objects.get(codigo=codigo),
                horas_inasistidas=Decimal(horas),
            )

        registrar(date(2026, 3, 10), 'I', '2')
        registrar(date(2026, 3, 11), 'PR', '1')
        registrar(date(2026, 3, 12), 'LIC', '2')  # ya cuenta como licencia
        registrar(date(2026, 4, 1), 'I', '2')  # otro mes

        cls.lector = get_user_model().objects.create_user(
            username='lector', password='x',
        )
        cls.lector.user_permissions.add(
            Permission.objects.get(codename='view_licenciaotorgada'),
        )

    def test_el_reporte_incluye_las_inasistencias_por_designacion(self):
        from decimal import Decimal

        self.client.force_login(self.lector)
        respuesta = self.client.get(
            reverse('licencias:reporte_mensual_licencias', args=[2026, 3]),
        )

        self.assertEqual(respuesta.status_code, 200)
        filas = respuesta.context['inasistencias']
        self.assertEqual(len(filas), 1)
        fila = filas[0]
        self.assertEqual(fila['docente'], 'Faltadora, Docente')
        self.assertEqual(fila['espacio_curricular'], 'Álgebra')
        self.assertEqual(fila['cargo'], 'Hora cátedra')
        self.assertEqual(fila['dias'], 2)
        self.assertEqual(fila['horas'], Decimal('3'))
        self.assertEqual(
            respuesta.context['total_horas_inasistencias'], Decimal('3'),
        )

    def test_la_pantalla_muestra_la_seccion_de_inasistencias(self):
        self.client.force_login(self.lector)
        respuesta = self.client.get(
            reverse('licencias:reporte_mensual_licencias', args=[2026, 3]),
        )

        self.assertContains(respuesta, 'Inasistencias del registro diario')
        self.assertContains(respuesta, 'Faltadora, Docente')
        self.assertContains(respuesta, 'Álgebra')
        # Hay inasistencias aunque no haya licencias: no se esconde todo.
        self.assertNotContains(
            respuesta, 'No hay licencias que afecten a este mes',
        )