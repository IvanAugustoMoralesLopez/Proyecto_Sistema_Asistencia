"""
Seguimiento de pendientes: faltas sin resolver y licencias sin completar.
Plazo en días hábiles, posponer una sola vez y bloqueo de los cierres.
"""

from datetime import date, datetime
from decimal import Decimal
from unittest import mock

from django.core.exceptions import ValidationError

from .models import DiaNoLaborable, RegistroAsistencia
from .services import (
    ESTADO_AVISO,
    ESTADO_EN_PLAZO,
    ESTADO_VENCIDO,
    TIPO_FALTA,
    TIPO_LICENCIA,
    avisos_del_dia,
    cerrar_dia,
    pendientes,
    posponer_pendiente,
    resolver_pendiente,
)
from .services.pendientes import plazos
from .tests import LUNES, MARTES, BaseAsistenciaTests

VIERNES = date(2026, 9, 11)
MIERCOLES = date(2026, 9, 16)
JUEVES = date(2026, 9, 17)


def hoy_es(fecha):
    """Fija «hoy» para el servicio de pendientes."""
    return mock.patch(
        "asistencias.services.pendientes.timezone.localdate", return_value=fecha
    )


class PlazosTests(BaseAsistenciaTests):
    def test_un_viernes_avisa_el_lunes_y_vence_el_martes(self):
        self.assertEqual(plazos(VIERNES), (LUNES, MARTES))

    def test_un_feriado_del_calendario_no_cuenta(self):
        DiaNoLaborable.objects.create(fecha=MARTES, tipo="FERIADO", descripcion="Prueba")
        self.assertEqual(plazos(LUNES), (MIERCOLES, JUEVES))


class PendientesTests(BaseAsistenciaTests):
    def falta(self, fecha=LUNES):
        return self.guardar(
            fecha=fecha, marca=self.marca_i, horas_inasistidas=Decimal("2")
        )

    def test_una_falta_sin_formulario_queda_en_seguimiento(self):
        registro = self.falta()
        self.assertTrue(registro.seguimiento)
        with hoy_es(LUNES):
            lista = pendientes()
        self.assertEqual(len(lista), 1)
        self.assertEqual(lista[0]["tipo"], TIPO_FALTA)
        self.assertEqual(lista[0]["estado"], ESTADO_EN_PLAZO)

    def test_un_presente_no_genera_pendiente(self):
        registro = self.guardar()
        self.assertFalse(registro.seguimiento)
        self.assertEqual(pendientes(LUNES), [])

    def test_la_falta_con_formulario_recibido_nace_justificada(self):
        registro = self.guardar(
            marca=self.marca_i,
            horas_inasistidas=Decimal("2"),
            formulario_recibido=True,
            nro_formulario="",
        )
        self.assertEqual(
            registro.estado_justificacion,
            RegistroAsistencia.EstadoJustificacion.JUSTIFICADA,
        )
        self.assertEqual(pendientes(MARTES), [])

    def test_una_lic_sin_licencia_es_licencia_sin_completar(self):
        self.guardar(marca=self.marca_lic, horas_inasistidas=Decimal("2"))
        lista = pendientes(MARTES)
        self.assertEqual(lista[0]["tipo"], TIPO_LICENCIA)
        self.assertEqual(lista[0]["estado"], ESTADO_AVISO)

    def test_aviso_al_dia_siguiente_y_vencido_al_segundo(self):
        self.falta()
        self.assertEqual(pendientes(MARTES)[0]["estado"], ESTADO_AVISO)
        self.assertEqual(pendientes(MIERCOLES)[0]["estado"], ESTADO_VENCIDO)

    def test_posponer_una_sola_vez(self):
        self.falta()
        clave = pendientes(MARTES)[0]["clave"]
        with hoy_es(MARTES):
            posponer_pendiente(usuario=self.usuario, token=self.token, clave=clave)
            self.assertEqual(avisos_del_dia(MARTES), [])
            with self.assertRaises(ValidationError):
                posponer_pendiente(usuario=self.usuario, token=self.token, clave=clave)
        # Vencido: vuelve a aparecer y ya no se puede posponer.
        self.assertEqual(len(avisos_del_dia(MIERCOLES)), 1)
        with hoy_es(MIERCOLES):
            with self.assertRaises(ValidationError):
                posponer_pendiente(usuario=self.usuario, token=self.token, clave=clave)

    def test_llego_el_formulario_la_justifica_sin_numero(self):
        registro = self.falta()
        clave = pendientes(MIERCOLES)[0]["clave"]
        with hoy_es(MIERCOLES):
            resolver_pendiente(
                usuario=self.usuario, token=self.token, clave=clave,
                respuesta="formulario",
            )
        registro.refresh_from_db()
        self.assertEqual(registro.estado_justificacion, "JUSTIFICADA")
        self.assertEqual(registro.nro_formulario, "")
        self.assertEqual(pendientes(MIERCOLES), [])

    def test_no_llego_queda_injustificada_y_resuelta(self):
        registro = self.falta()
        clave = pendientes(MIERCOLES)[0]["clave"]
        with hoy_es(MIERCOLES):
            resolver_pendiente(
                usuario=self.usuario, token=self.token, clave=clave,
                respuesta="no_llego",
            )
        registro.refresh_from_db()
        self.assertEqual(registro.estado_justificacion, "INJUSTIFICADA")
        self.assertIsNotNone(registro.resuelto_en)
        self.assertEqual(pendientes(MIERCOLES), [])

    def test_licencia_que_no_corresponde_pasa_a_inasistencia(self):
        registro = self.guardar(marca=self.marca_lic, horas_inasistidas=Decimal("2"))
        clave = pendientes(MIERCOLES)[0]["clave"]
        with hoy_es(MIERCOLES):
            with self.assertRaises(ValidationError):
                resolver_pendiente(
                    usuario=self.usuario, token=self.token, clave=clave,
                    respuesta="no_corresponde", motivo="corto",
                )
            resolver_pendiente(
                usuario=self.usuario, token=self.token, clave=clave,
                respuesta="no_corresponde",
                motivo="No trajo ningún certificado médico",
            )
        registro.refresh_from_db()
        self.assertEqual(registro.marca.codigo, "I")
        lista = pendientes(MIERCOLES)
        self.assertEqual(lista[0]["tipo"], TIPO_FALTA)

    def test_cargar_la_licencia_saca_el_pendiente(self):
        registro = self.guardar(marca=self.marca_lic, horas_inasistidas=Decimal("2"))
        licencia = self.crear_licencia(desde=LUNES, hasta=LUNES)
        RegistroAsistencia.objects.filter(pk=registro.pk).update(licencia=licencia)
        self.assertEqual(pendientes(MIERCOLES), [])

    def test_un_vencido_no_deja_cerrar_la_jornada(self):
        self.falta()
        with mock.patch(
            "asistencias.services.cierres.timezone.localdate",
            return_value=MIERCOLES,
        ):
            with self.assertRaises(ValidationError) as error:
                cerrar_dia(usuario=self.usuario, token=self.token, fecha=MIERCOLES)
        self.assertIn("PEREZ, JUAN", str(error.exception))

    def test_los_registros_viejos_no_tienen_seguimiento(self):
        RegistroAsistencia.objects.create(
            designacion=self.designacion,
            fecha=LUNES,
            marca=self.marca_i,
            horas_inasistidas=Decimal("2"),
            estado_justificacion="INJUSTIFICADA",
        )
        self.assertEqual(pendientes(MIERCOLES), [])


class DiariaConPendientesTests(BaseAsistenciaTests):
    """La carga diaria: apartado de inasistencia, avisos y resolución."""

    def setUp(self):
        super().setUp()
        from django.urls import reverse

        self.client.force_login(self.usuario)
        self.url = reverse("asistencia:planilla_rapida")
        self.url_resolver = reverse("asistencia:resolver_pendiente")

    def enviar(self, **campos):
        dni = self.persona.dni
        datos = {
            "fecha": LUNES.isoformat(),
            f"agente-marca-{dni}": str(self.marca_i.pk),
            f"agente-horas-{dni}": "2",
        }
        datos.update(campos)
        return self.client.post(self.url, datos)

    def test_falta_con_formulario_recibido_queda_justificada(self):
        dni = self.persona.dni
        self.enviar(**{f"agente-form-{dni}": "si", f"agente-nroform-{dni}": ""})
        registro = RegistroAsistencia.objects.get(fecha=LUNES)
        self.assertEqual(registro.estado_justificacion, "JUSTIFICADA")
        self.assertFalse(registro.seguimiento)

    def test_falta_sin_formulario_queda_pendiente_y_avisa(self):
        dni = self.persona.dni
        self.enviar(**{f"agente-form-{dni}": "no"})
        registro = RegistroAsistencia.objects.get(fecha=LUNES)
        self.assertTrue(registro.seguimiento)
        # Hoy (real) ya pasó el plazo: el aviso es obligatorio.
        respuesta = self.client.get(self.url, {"fecha": LUNES.isoformat()})
        self.assertContains(respuesta, "Falta sin resolver")
        self.assertContains(respuesta, "hay que responder hoy")

    def test_resolver_desde_el_aviso(self):
        self.enviar()
        clave = pendientes()[0]["clave"]
        respuesta = self.client.post(
            self.url_resolver,
            {"clave": clave, "accion": "resolver", "respuesta": "no_llego", "volver": self.url},
        )
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(pendientes(), [])

    def test_el_volver_no_acepta_otro_sitio(self):
        self.enviar()
        clave = pendientes()[0]["clave"]
        respuesta = self.client.post(
            self.url_resolver,
            {"clave": clave, "accion": "resolver", "respuesta": "no_llego",
             "volver": "https://otro-sitio.example/"},
        )
        self.assertNotIn("otro-sitio", respuesta["Location"])

    def test_la_lic_sin_licencia_ofrece_cargarla(self):
        respuesta = self.client.get(self.url, {"fecha": LUNES.isoformat()})
        self.assertContains(respuesta, "Cargar licencia ahora")


class BandejaLicenciasTests(BaseAsistenciaTests):
    """Licencias › Pendientes: la misma lista que la diaria, con filtros."""

    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import Permission
        from django.urls import reverse

        self.usuario.user_permissions.add(
            Permission.objects.get(codename="view_licenciaotorgada")
        )
        self.client.force_login(self.usuario)
        self.url = reverse("licencias:pendientes")
        self.guardar(fecha=LUNES, marca=self.marca_i, horas_inasistidas=Decimal("2"))

    def test_muestra_la_falta_y_los_contadores(self):
        with hoy_es(MIERCOLES):
            respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context["contadores"]["total"], 1)
        self.assertEqual(respuesta.context["contadores"]["vencidos"], 1)
        self.assertContains(respuesta, "Falta sin resolver")

    def test_filtra_por_estado_y_por_docente(self):
        with hoy_es(MIERCOLES):
            self.assertEqual(
                self.client.get(self.url, {"estado": "aviso"}).context["lista_pendientes"], []
            )
            self.assertEqual(
                len(self.client.get(self.url, {"docente": self.persona.dni}).context["lista_pendientes"]), 1
            )
            self.assertEqual(
                self.client.get(self.url, {"docente": "zzz"}).context["lista_pendientes"], []
            )

    def test_sin_permiso_de_licencias_no_entra(self):
        from django.contrib.auth.models import Permission

        self.usuario.user_permissions.remove(
            Permission.objects.get(codename="view_licenciaotorgada")
        )
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get(self.url).status_code, 403)


class AvisoLicPendienteTests(BaseAsistenciaTests):
    def setUp(self):
        super().setUp()
        from django.urls import reverse

        self.client.force_login(self.usuario)
        self.url = reverse("asistencia:planilla_rapida")

    def test_la_diaria_ofrece_continuar_sin_cargar_con_las_fechas_del_plazo(self):
        respuesta = self.client.get(self.url, {"fecha": LUNES.isoformat()})
        self.assertEqual(respuesta.context["plazo_aviso"], MARTES)
        self.assertEqual(respuesta.context["plazo_vence"], MIERCOLES)
        self.assertContains(respuesta, "Continuar sin cargar")
        self.assertContains(respuesta, 'id="modal-lic-pendiente"')
        self.assertContains(respuesta, 'class="btn-check"')
