from datetime import date

from django.contrib.auth.models import Permission, User

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from personal.models import Cargo, Designacion, Persona

from .clasificacion import (
    CATEGORIAS_POR_PLANILLA,
    CategoriaSinPlanillaError,
    PLANILLA_IL01,
    PLANILLA_IL02,
    planilla_para_categoria,
)
from .dias import contar_dias_habiles, listar_dias_habiles, rango_en_anio
from .models import LicenciaArticulo, LicenciaOtorgada
from .services import dias_usados_en_anio

class DiasHabilesTests(SimpleTestCase):
    # 26/10/2026 es lunes; 31/10 sábado; 01/11 domingo.

    def test_semana_completa_cuenta_cinco(self):
        self.assertEqual(contar_dias_habiles(date(2026, 10, 26), date(2026, 11, 1), set()), 5)

    def test_feriado_en_dia_habil_se_descuenta(self):
        feriados = {date(2026, 10, 28)}
        self.assertEqual(contar_dias_habiles(date(2026, 10, 26), date(2026, 11, 1), feriados), 4)

    def test_feriado_en_fin_de_semana_no_descuenta_dos_veces(self):
        feriados = {date(2026, 10, 31)}
        self.assertEqual(contar_dias_habiles(date(2026, 10, 26), date(2026, 11, 1), feriados), 5)

    def test_solo_fin_de_semana_da_cero(self):
        self.assertEqual(contar_dias_habiles(date(2026, 10, 31), date(2026, 11, 1), set()), 0)

    def test_rango_invertido_da_cero(self):
        self.assertEqual(contar_dias_habiles(date(2026, 11, 2), date(2026, 10, 26), set()), 0)

    def test_un_solo_dia_habil(self):
        self.assertEqual(listar_dias_habiles(date(2026, 10, 28), date(2026, 10, 28), set()),
                         [date(2026, 10, 28)])


class RangoEnAnioTests(SimpleTestCase):
    def test_licencia_que_cruza_de_anio_se_recorta(self):
        desde, hasta = date(2025, 12, 15), date(2026, 1, 10)
        self.assertEqual(rango_en_anio(desde, hasta, 2025), (date(2025, 12, 15), date(2025, 12, 31)))
        self.assertEqual(rango_en_anio(desde, hasta, 2026), (date(2026, 1, 1), date(2026, 1, 10)))

    def test_licencia_fuera_del_anio_da_none(self):
        self.assertIsNone(rango_en_anio(date(2024, 3, 1), date(2024, 3, 10), 2026))

    def test_licencia_abierta_se_acota_a_hoy(self):
        hoy = date(2026, 3, 10)
        self.assertEqual(rango_en_anio(date(2026, 2, 1), None, 2026, hoy), (date(2026, 2, 1), hoy))

    def test_licencia_abierta_de_anio_pasado_llega_a_fin_de_ese_anio(self):
        hoy = date(2026, 3, 10)
        self.assertEqual(rango_en_anio(date(2025, 6, 1), None, 2025, hoy),
                         (date(2025, 6, 1), date(2025, 12, 31)))

    def test_licencia_abierta_que_empieza_en_el_futuro_da_none(self):
        self.assertIsNone(rango_en_anio(date(2027, 1, 1), None, 2026, date(2026, 10, 28)))


class ClasificacionTests(SimpleTestCase):
    def test_rn04_salud_va_a_il01(self):
        for categoria in ('Enfermedad común', 'Corto tratamiento',
                          'Largo tratamiento', 'Enfermedad familiar'):
            self.assertEqual(planilla_para_categoria(categoria), PLANILLA_IL01)

    def test_rn05_administrativas_van_a_il02(self):
        for categoria in ('Razones particulares', 'Examen', 'Duelo',
                          'Matrimonio', 'Compensatorio', 'Comisión de servicio'):
            self.assertEqual(planilla_para_categoria(categoria), PLANILLA_IL02)

    def test_categoria_desconocida_no_se_clasifica_sola(self):
        with self.assertRaises(CategoriaSinPlanillaError):
            planilla_para_categoria('Otros')

    def test_ninguna_categoria_esta_en_las_dos_planillas(self):
        il01 = set(CATEGORIAS_POR_PLANILLA[PLANILLA_IL01])
        il02 = set(CATEGORIAS_POR_PLANILLA[PLANILLA_IL02])
        self.assertFalse(il01 & il02)


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