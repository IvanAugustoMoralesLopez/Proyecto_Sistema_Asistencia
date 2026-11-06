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