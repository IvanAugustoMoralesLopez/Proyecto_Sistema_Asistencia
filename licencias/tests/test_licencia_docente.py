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

    def test_licencia_se_distingue_y_aplica_a_una_materia_en_dos_carreras(self):
        from personal.models import Carrera, Designacion, EspacioCurricular, Horario

        carrera_a = Carrera.objects.get(nombre="TSDS")
        carrera_b = Carrera.objects.create(nombre="TSGA")
        materia = EspacioCurricular.objects.create(nombre="Legislación Laboral")
        materia.carreras.add(carrera_a, carrera_b)
        titular = Designacion.objects.create(
            persona=self.zarate,
            cargo=self.cargo,
            espacio_curricular=materia,
            carrera=carrera_a,
            situacion_revista="TIT",
            desde=date(2026, 3, 1),
        )
        suplente = Designacion.objects.create(
            persona=self.zarate,
            cargo=self.cargo,
            espacio_curricular=materia,
            carrera=carrera_b,
            situacion_revista="SUP",
            desde=date(2026, 3, 1),
        )
        for designacion in (titular, suplente):
            Horario.objects.create(
                designacion=designacion, dia="MIE", horas_catedra=2
            )

        previa = self.client.get(
            self.url,
            {
                "persona": self.zarate.pk,
                "desde": "2026-10-21",
                "hasta": "2026-10-21",
                "articulo": self.enfermedad.pk,
            },
        )
        self.assertEqual(previa.status_code, 200)
        self.assertContains(previa, "Legislación Laboral (TSDS)")
        self.assertContains(previa, "Legislación Laboral (TSGA)")

        respuesta = self.client.post(
            self.url,
            self.datos(
                desde="2026-10-21",
                hasta="2026-10-21",
                designaciones=[str(titular.pk), str(suplente.pk)],
            ),
        )

        self.assertEqual(respuesta.status_code, 302)
        licencias = list(
            LicenciaOtorgada.objects.filter(
                designacion__in=(titular, suplente)
            ).select_related("designacion", "articulo")
        )
        self.assertEqual(len(licencias), 2)
        self.assertEqual(
            {licencia.designacion_id for licencia in licencias},
            {titular.pk, suplente.pk},
        )
        self.assertEqual(
            {licencia.designacion.carrera_id for licencia in licencias},
            {carrera_a.pk, carrera_b.pk},
        )
        self.assertEqual(
            {licencia.sit_rev for licencia in licencias},
            {"Titular", "Suplente"},
        )
        self.assertEqual(len({licencia.grupo for licencia in licencias}), 1)
        self.assertEqual(
            set(
                RegistroAsistencia.objects.filter(
                    designacion__in=(titular, suplente),
                    fecha=MIE_21,
                    marca__codigo="LIC",
                ).values_list("designacion_id", flat=True)
            ),
            {titular.pk, suplente.pk},
        )

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

    def test_es_todo_o_nada_si_una_materia_no_tiene_articulo(self):
        # No hay artículo 14 para interinos: Materia 2 no se puede encuadrar.
        self.m2.situacion_revista = "INT"
        self.m2.save()
        respuesta = self.client.post(self.url, self.datos())
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Materia 2: el nomenclador no tiene")
        self.assertEqual(LicenciaOtorgada.objects.count(), 0)

    def test_cada_materia_lleva_el_articulo_de_su_situacion(self):
        # Materia 2 es de suplente: lleva el S-14, con la misma disposición.
        self.m2.situacion_revista = "SUP"
        self.m2.save()
        self.client.post(self.url, self.datos())
        por_materia = {
            l.designacion_id: l for l in LicenciaOtorgada.objects.all()
        }
        self.assertEqual(por_materia[self.m1.pk].articulo, self.enfermedad)
        self.assertEqual(por_materia[self.m2.pk].articulo, self.enfermedad_sup)
        self.assertEqual(por_materia[self.m2.pk].sit_rev, "Suplente")
        self.assertEqual(
            {l.disp_numero for l in por_materia.values()}, {"7"}
        )

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


class AtajoMotivoTests(BaseLicenciaDocente):
    """Nueva licencia: últimas licencias del docente y motivos frecuentes."""

    def test_sin_licencias_muestra_los_motivos_frecuentes(self):
        # Abel pidió una licencia por razones particulares; Zárate nunca pidió.
        LicenciaOtorgada.objects.create(
            designacion=self.m3, articulo=self.particulares, sit_rev="Titular",
            desde=date(2026, 10, 1), hasta=date(2026, 10, 1),
        )
        respuesta = self.client.get(self.url, {"persona": self.zarate.pk, "desde": "2026-10-21"})
        self.assertEqual(respuesta.context["ultimas"], [])
        self.assertEqual([f["nombre"] for f in respuesta.context["frecuentes"]], ["Razones particulares"])
        self.assertContains(respuesta, "no tiene licencias anteriores")

    def test_muestra_las_ultimas_y_el_atajo_elige_el_motivo(self):
        self.client.post(self.url, self.datos())  # enfermedad, 21 al 23/10
        respuesta = self.client.get(self.url, {"persona": self.zarate.pk, "desde": "2026-11-09"})
        (ultima,) = respuesta.context["ultimas"]
        self.assertEqual(ultima["nombre"], "Enfermedad común")
        self.assertEqual(ultima["materias"], 2)
        self.assertEqual(ultima["desde"], MIE_21)

        respuesta = self.client.post(self.url, {
            "atajo": self.enfermedad.pk, "persona": self.zarate.pk,
            "desde": "2026-11-11", "hasta": "2026-11-12",
        })
        self.assertEqual(respuesta.context["articulo_elegido"], self.enfermedad)
        self.assertContains(respuesta, "Usando este motivo")
        self.assertEqual(LicenciaOtorgada.objects.count(), 2)  # el atajo no guarda

    def test_la_materia_sin_articulo_queda_destildada(self):
        self.m2.situacion_revista = "INT"
        self.m2.save()
        respuesta = self.client.get(self.url, {
            "persona": self.zarate.pk, "desde": "2026-10-21", "articulo": self.enfermedad.pk,
        })
        por_materia = {m["materia"]: m for m in respuesta.context["materias"]}
        self.assertTrue(por_materia["Materia 2"]["sin_articulo"])
        self.assertEqual(por_materia["Materia 1"]["articulo"], self.enfermedad)
        self.assertNotIn(str(self.m2.pk), respuesta.context["form"]["designaciones"].value())
