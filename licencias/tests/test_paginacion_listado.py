from datetime import date, timedelta

from django.contrib.auth.models import Permission, User
from django.test import TestCase

from licencias.models import LicenciaArticulo, LicenciaOtorgada
from personal.models import Cargo, Designacion, Persona


class ListadoPaginacionTests(TestCase):
    """El listado se muestra de a 20 licencias por página."""

    @classmethod
    def setUpTestData(cls):
        cargo = Cargo.objects.create(codigo='HC', descripcion='Hora cátedra')
        gomez = Persona.objects.create(dni=99000096, apellido_nombre='Gomez, Ana')
        ruiz = Persona.objects.create(dni=99000095, apellido_nombre='Ruiz, Luis')
        d_gomez = Designacion.objects.create(
            persona=gomez, cargo=cargo, desde=date(2026, 1, 1),
        )
        d_ruiz = Designacion.objects.create(
            persona=ruiz, cargo=cargo, desde=date(2026, 1, 1),
        )
        articulo = LicenciaArticulo.objects.create(
            cod_licencia='A-1', articulo='1', tipo_licencia='Uno',
            categoria_informe='Duelo', sit_rev='Titular',
            goce_haberes='Con goce de haberes', autoridad='Dirección',
            plazo='Según artículo',
        )
        # 25 licencias de un día cada una, sin superponerse:
        # 22 de Gomez y 3 de Ruiz.
        for i in range(25):
            dia = date(2026, 1, 1) + timedelta(days=i)
            LicenciaOtorgada.objects.create(
                designacion=d_gomez if i < 22 else d_ruiz,
                articulo=articulo, sit_rev='Titular', desde=dia, hasta=dia,
            )
        usuario = User.objects.create_user('lector', password='x')
        usuario.user_permissions.add(
            Permission.objects.get(
                content_type__app_label='licencias', codename='view_licenciaotorgada',
            )
        )

    def setUp(self):
        self.client.login(username='lector', password='x')

    def _pagina(self, parametros=''):
        respuesta = self.client.get('/licencias/listado/' + parametros)
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def _ids(self, respuesta):
        return [licencia.pk for licencia in respuesta.context['licencias']]

    def test_la_primera_pagina_muestra_20_y_la_segunda_las_5_restantes(self):
        self.assertEqual(len(self._ids(self._pagina())), 20)
        self.assertEqual(len(self._ids(self._pagina('?page=2'))), 5)

    def test_ninguna_licencia_se_repite_ni_se_pierde(self):
        primera = self._ids(self._pagina('?page=1'))
        segunda = self._ids(self._pagina('?page=2'))
        self.assertEqual(len(set(primera + segunda)), 25)

    def test_indica_en_que_pagina_esta(self):
        self.assertContains(self._pagina(), 'Página 1 de 2')
        self.assertContains(self._pagina('?page=2'), 'Página 2 de 2')

    def test_una_pagina_invalida_no_rompe_el_listado(self):
        # No numérica: va a la primera. Fuera de rango: va a la última.
        self.assertEqual(len(self._ids(self._pagina('?page=abc'))), 20)
        self.assertEqual(len(self._ids(self._pagina('?page=99'))), 5)

    def test_con_una_sola_pagina_no_se_muestra_el_paginador(self):
        respuesta = self._pagina('?docente=ruiz')
        self.assertEqual(len(self._ids(respuesta)), 3)
        self.assertNotContains(respuesta, 'Página 1 de')

    def test_los_filtros_se_conservan_al_cambiar_de_pagina(self):
        respuesta = self._pagina('?docente=gomez')
        self.assertEqual(len(self._ids(respuesta)), 20)
        self.assertContains(respuesta, 'docente=gomez&page=2')
        self.assertEqual(len(self._ids(self._pagina('?docente=gomez&page=2'))), 2)