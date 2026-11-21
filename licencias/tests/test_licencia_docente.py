"""
Licencia por docente: un pedido, una licencia por materia afectada, todas
con el mismo grupo y la misma disposición (RN-11). Prórroga y corte.
"""
from datetime import date

from django.contrib.auth.models import Permission
from django.urls import reverse

from asistencias.models import RegistroAsistencia
from licencias.licencia_docente import cortar, materias_afectadas, prorrogar
from licencias.models import LicenciaOtorgada
from licencias.services import dias_usados_en_anio

from .test_planilla_mensual import BasePlanillaMensual

MIE_21 = date(2026, 10, 21)
JUE_22 = date(2026, 10, 22)
VIE_23 = date(2026, 10, 23)


class BaseLicenciaDocente(BasePlanillaMensual):
    def setUp(self):
        self.usuario.user_permissions.add(
            Permission.objects.get(codename="add_licenciaotorgada")
        )
        self.client.force_login(self.usuario)
        self.url = reverse("licencias:nueva_licencia")

    def datos(self, **cambios):
        datos = {
            "accion": "guardar",
            "persona": self.zarate.pk,
            "articulo": self.enfermedad.pk,
            "desde": "2026-10-21",
            "hasta": "2026-10-23",
            "designaciones": [self.m1.pk, self.m2.pk],
            "disp_tipo": "",
            "disp_oficina": "1452",
            "disp_numero": "7",
            "disp_anio": "2026",
        }
        datos.update(cambios)
        return datos


class LicenciaDocenteTests(BaseLicenciaDocente):
    def test_calcula_las_materias_afectadas_con_sus_dias(self):
        materias = materias_afectadas(self.zarate, MIE_21, VIE_23)
        por_materia = {m["materia"]: m for m in materias}
        self.assertEqual(por_materia["Materia 1"]["dias"], [MIE_21, JUE_22])
        self.assertEqual(por_materia["Materia 2"]["dias"], [JUE_22, VIE_23])
        self.assertEqual(por_materia["Materia 1"]["horas"], 5)

    def test_la_pantalla_precarga_docente_materias_y_numero(self):
        respuesta = self.client.get(
            self.url, {"persona": self.zarate.pk, "desde": "2026-10-21"}
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Materia 1")
        self.assertContains(respuesta, "Materia 2")
        self.assertEqual(respuesta.context["form"].initial["disp_numero"], "1")

    def test_llegar_con_la_designacion_trae_al_docente(self):
        respuesta = self.client.get(
            self.url, {"designacion": self.m1.pk, "desde": "2026-10-22"}
        )
        self.assertEqual(respuesta.context["persona"], self.zarate)

    def test_guarda_una_licencia_por_materia_con_la_misma_disposicion(self):
        respuesta = self.client.post(self.url, self.datos())
        self.assertEqual(respuesta.status_code, 302)
        licencias = list(LicenciaOtorgada.objects.order_by("designacion_id"))
        self.assertEqual(len(licencias), 2)
        self.assertEqual(licencias[0].grupo, licencias[1].grupo)
        self.assertEqual({l.disp_numero for l in licencias}, {"7"})
        # La diaria queda marcada con LIC en los días con clase de cada materia.
        marcados = set(
            RegistroAsistencia.objects.filter(marca__codigo="LIC").values_list(
                "designacion_id", "fecha"
            )
        )
        self.assertEqual(
            marcados,
            {(self.m1.pk, MIE_21), (self.m1.pk, JUE_22), (self.m2.pk, JUE_22), (self.m2.pk, VIE_23)},
        )

    def test_un_numero_de_disposicion_usado_no_se_repite(self):
        self.client.post(self.url, self.datos())
        respuesta = self.client.post(
            self.url,
            self.datos(persona=self.abel.pk, designaciones=[self.m3.pk], desde="2026-10-29", hasta="2026-10-29"),
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "ya la usa")
        self.assertEqual(LicenciaOtorgada.objects.count(), 2)

    def test_es_todo_o_nada_si_una_materia_no_cumple(self):
        self.m2.situacion_revista = "SUP"
        self.m2.save()
        respuesta = self.client.post(self.url, self.datos())
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Materia 2")
        self.assertEqual(LicenciaOtorgada.objects.count(), 0)

    def test_el_tope_cuenta_dias_del_docente_no_licencias(self):
        self.client.post(self.url, self.datos())
        # 21, 22 y 23: tres días hábiles aunque sean dos materias.
        self.assertEqual(dias_usados_en_anio(self.zarate.dni, "14", 2026), 3)

    def test_completar_la_licencia_resuelve_la_lic_pendiente(self):
        from asistencias.services import pendientes

        registro = self.marcar(self.m1, MIE_21, "LIC", "2", seguimiento=True)
        self.assertEqual(len(pendientes(VIE_23)), 1)
        self.client.post(self.url, self.datos())
        registro.refresh_from_db()
        self.assertIsNotNone(registro.licencia_id)
        self.assertEqual(pendientes(VIE_23), [])

    def test_prorrogar_y_cortar(self):
        self.client.post(self.url, self.datos())
        grupo = list(LicenciaOtorgada.objects.order_by("designacion_id"))
        prorrogar(grupo, date(2026, 10, 29))
        self.assertEqual({l.hasta for l in grupo}, {date(2026, 10, 29)})

        liberados, avisos = cortar(grupo, JUE_22, self.usuario)
        self.assertEqual({l.hasta for l in grupo}, {MIE_21})
        self.assertEqual(liberados, [JUE_22, VIE_23])
        self.assertEqual(
            RegistroAsistencia.objects.filter(marca__codigo="LIC").count(), 1
        )

    def test_el_detalle_muestra_el_pedido_completo(self):
        self.client.post(self.url, self.datos())
        licencia = LicenciaOtorgada.objects.first()
        respuesta = self.client.get(
            reverse("licencias:detalle_licencia", args=[licencia.pk])
        )
        self.assertContains(respuesta, "Materia 1")
        self.assertContains(respuesta, "Materia 2")
        self.assertContains(respuesta, "N° 7/2026")


class DisposicionesEditablesTests(BaseLicenciaDocente):
    def test_corregir_el_numero_cambia_renglones_y_licencias(self):
        from licencias.models import RenglonMensual

        self.client.post(self.url, self.datos())
        planilla = reverse("licencias:planilla_mensual", args=[2026, 10])
        self.client.post(planilla, {"accion": "procesar"})
        self.assertEqual(
            set(RenglonMensual.objects.values_list("disp_numero", flat=True)), {"7"}
        )
        self.client.post(
            planilla,
            {"accion": "disposiciones", "disp-numero-2026-7": "9", "disp-oficina-2026-7": "1452"},
        )
        self.assertEqual(
            set(RenglonMensual.objects.values_list("disp_numero", flat=True)), {"9"}
        )
        self.assertEqual(
            set(LicenciaOtorgada.objects.values_list("disp_numero", flat=True)), {"9"}
        )

    def test_no_deja_repetir_un_numero_de_otra_disposicion(self):
        from licencias.models import RenglonMensual

        self.client.post(self.url, self.datos())
        self.client.post(
            self.url,
            self.datos(persona=self.abel.pk, designaciones=[self.m3.pk],
                       desde="2026-10-22", hasta="2026-10-22", disp_numero="8"),
        )
        planilla = reverse("licencias:planilla_mensual", args=[2026, 10])
        self.client.post(planilla, {"accion": "procesar"})
        self.client.post(
            planilla,
            {"accion": "disposiciones", "disp-numero-2026-8": "7", "disp-oficina-2026-8": "1452"},
        )
        self.assertEqual(
            set(RenglonMensual.objects.filter(designacion=self.m3).values_list("disp_numero", flat=True)),
            {"8"},
        )
