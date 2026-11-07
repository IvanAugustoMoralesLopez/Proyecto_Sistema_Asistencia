from django.test import TestCase


class PantallasDePruebaTests(TestCase):
    """Las maquetas ya no se sirven: no deben abrirse sin iniciar sesión."""

    def test_las_maquetas_no_existen(self):
        for ruta in ('/pantallas/licencias/', '/pantallas/informe/'):
            with self.subTest(ruta=ruta):
                self.assertEqual(self.client.get(ruta).status_code, 404)