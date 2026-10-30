from datetime import date

from django.test import SimpleTestCase

from .clasificacion import (
    CATEGORIAS_POR_PLANILLA,
    CategoriaSinPlanillaError,
    PLANILLA_IL01,
    PLANILLA_IL02,
    planilla_para_categoria,
)
from .dias import contar_dias_habiles, listar_dias_habiles, rango_en_anio


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
