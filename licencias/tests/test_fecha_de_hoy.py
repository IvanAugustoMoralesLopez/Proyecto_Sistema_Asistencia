from datetime import date
from unittest import mock

from django.test import TestCase

from licencias.models import LicenciaArticulo, LicenciaOtorgada
from licencias.services import dias_usados_en_anio
from personal.models import Cargo, Designacion, Persona

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

