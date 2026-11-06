from datetime import date

from django.test import TestCase
from django.urls import reverse

from licencias.models import LicenciaArticulo, LicenciaOtorgada
from personal.models import Cargo, Designacion, Persona


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

    def test_la_etiqueta_de_la_designacion_incluye_su_situacion_de_revista(self):
        from licencias.forms import LicenciaOtorgadaForm
        html = str(LicenciaOtorgadaForm()['designacion'])
        self.assertIn(' - Interino</option>', html)

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
