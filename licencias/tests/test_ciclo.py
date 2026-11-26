"""RN-08: ciclo lectivo de marzo a febrero (mes de inicio en los parámetros)."""

from datetime import date

from django.test import TestCase

from licencias.dias import ciclo_de, limites_del_ciclo, rango_en_ciclo


class CicloLectivoTests(TestCase):
    def setUp(self):
        from reportes.models import ParametroSistema

        parametros = ParametroSistema.obtener()
        parametros.mes_inicio_ciclo = 3
        parametros.save()

    def test_por_defecto_es_el_anio_calendario(self):
        from reportes.models import ParametroSistema

        ParametroSistema.objects.all().delete()
        self.assertEqual(ParametroSistema.obtener().mes_inicio_ciclo, 1)
        self.assertEqual(ciclo_de(date(2027, 2, 10)), 2027)

    def test_febrero_es_del_ciclo_anterior(self):
        self.assertEqual(ciclo_de(date(2027, 2, 10)), 2026)
        self.assertEqual(ciclo_de(date(2027, 3, 1)), 2027)

    def test_limites_de_marzo_a_febrero(self):
        self.assertEqual(limites_del_ciclo(2026), (date(2026, 3, 1), date(2027, 2, 28)))
        self.assertEqual(limites_del_ciclo(2027), (date(2027, 3, 1), date(2028, 2, 29)))

    def test_con_mes_1_es_el_anio_calendario(self):
        self.assertEqual(limites_del_ciclo(2026, 1), (date(2026, 1, 1), date(2026, 12, 31)))
        self.assertEqual(ciclo_de(date(2027, 2, 10), 1), 2027)

    def test_rango_recortado_al_ciclo(self):
        self.assertEqual(
            rango_en_ciclo(date(2027, 2, 23), date(2027, 3, 5), 2026),
            (date(2027, 2, 23), date(2027, 2, 28)),
        )
        self.assertIsNone(rango_en_ciclo(date(2025, 3, 1), date(2025, 3, 10), 2026))
