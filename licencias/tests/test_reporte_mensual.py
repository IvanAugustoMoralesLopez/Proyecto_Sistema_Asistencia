"""
El reporte por licencias fue reemplazado por la planilla mensual IL-01 /
IL-02 (ver test_planilla_mensual.py). La dirección vieja se conserva y
redirige, para que los enlaces guardados no den error.
"""
from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse


class ReporteViejoRedirigeTests(TestCase):
    def test_redirige_a_la_planilla_del_mismo_mes(self):
        usuario = User.objects.create_user(username='lector', password='x')
        usuario.user_permissions.add(Permission.objects.get(codename='view_licenciaotorgada'))
        self.client.force_login(usuario)

        respuesta = self.client.get(
            reverse('licencias:reporte_mensual_licencias', args=[2026, 3])
        )
        self.assertRedirects(
            respuesta,
            reverse('licencias:planilla_mensual', args=[2026, 3]),
            fetch_redirect_response=False,
        )

    def test_sigue_pidiendo_login_y_permiso(self):
        url = reverse('licencias:reporte_mensual_licencias', args=[2026, 3])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(User.objects.create_user(username='nadie', password='x'))
        self.assertEqual(self.client.get(url).status_code, 403)
