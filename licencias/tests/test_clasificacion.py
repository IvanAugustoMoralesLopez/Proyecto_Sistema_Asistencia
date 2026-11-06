from django.test import SimpleTestCase

from licencias.clasificacion import (
    CATEGORIAS_POR_PLANILLA,
    CategoriaSinPlanillaError,
    PLANILLA_IL01,
    PLANILLA_IL02,
    planilla_para_categoria,
) 

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