from datetime import date

from django.test import SimpleTestCase

from licencias.dias import contar_dias_habiles, listar_dias_habiles, mes_vecino, rango_en_anio 


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

class MesVecinoTests(SimpleTestCase):
    def test_mes_siguiente_dentro_del_anio(self):
        self.assertEqual(mes_vecino(2026, 5, 1), (2026, 6))

    def test_mes_anterior_dentro_del_anio(self):
        self.assertEqual(mes_vecino(2026, 5, -1), (2026, 4))

    def test_diciembre_pasa_a_enero_del_anio_siguiente(self):
        self.assertEqual(mes_vecino(2026, 12, 1), (2027, 1))

    def test_enero_vuelve_a_diciembre_del_anio_anterior(self):
        self.assertEqual(mes_vecino(2026, 1, -1), (2025, 12))

    def test_sin_desplazamiento_devuelve_el_mismo_mes(self):
        self.assertEqual(mes_vecino(2026, 3, 0), (2026, 3)) 


