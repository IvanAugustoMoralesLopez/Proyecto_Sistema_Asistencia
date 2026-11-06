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