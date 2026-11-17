"""
Planilla mensual generada desde la asistencia diaria (Documento de
Requerimientos v2.0): RF-12, RF-13, RF-14, RF-15, RF-16, RN-04, RN-05,
RN-06, RN-07, RN-08, RN-10 y RN-11.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from asistencias.models import EventoAsistencia, MarcaAsistencia, RegistroAsistencia
from licencias.models import LicenciaArticulo, LicenciaOtorgada, RenglonMensual
from licencias.planilla_mensual import (
    cuadros_del_mes,
    emitir_disposiciones_planilla,
    imputar_renglones,
    procesar_mes,
)
from personal.models import Cargo, Carrera, Designacion, EspacioCurricular, Horario, Persona


class BasePlanillaMensual(TestCase):
    """
    ZARATE dicta Materia 1 (MIE 2 h, JUE 3 h) y Materia 2 (JUE 4 h, VIE 2 h).
    ABEL dicta Materia 3 (JUE 2 h). Octubre de 2026: 21 mié, 22 jue, 23 vie.
    """

    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user("bedel", password="x")
        cls.usuario.user_permissions.add(
            Permission.objects.get(codename="view_licenciaotorgada"),
            Permission.objects.get(codename="change_licenciaotorgada"),
        )
        carrera = Carrera.objects.create(nombre="TSDS")
        cls.cargo = Cargo.objects.create(codigo="HC", descripcion="Hora cátedra")
        cls.zarate = Persona.objects.create(dni="30111222", apellido_nombre="Zárate, Ana")
        cls.abel = Persona.objects.create(dni="28999888", apellido_nombre="Abel, Luis")

        def designacion(persona, materia, horarios, situacion="TIT"):
            espacio = EspacioCurricular.objects.create(nombre=materia, carrera=carrera)
            nueva = Designacion.objects.create(
                persona=persona, cargo=cls.cargo, espacio_curricular=espacio,
                situacion_revista=situacion, desde=date(2026, 3, 1),
            )
            for dia, horas in horarios:
                Horario.objects.create(designacion=nueva, dia=dia, horas_catedra=horas)
            return nueva

        cls.m1 = designacion(cls.zarate, "Materia 1", [("MIE", 2), ("JUE", 3)])
        cls.m2 = designacion(cls.zarate, "Materia 2", [("JUE", 4), ("VIE", 2)])
        cls.m3 = designacion(cls.abel, "Materia 3", [("JUE", 2)])

        def articulo(codigo, numero, tipo, categoria, situacion="Titular"):
            return LicenciaArticulo.objects.create(
                cod_licencia=codigo, articulo=numero, tipo_licencia=tipo,
                categoria_informe=categoria, sit_rev=situacion,
                goce_haberes="Con goce", autoridad="Dirección", plazo="-",
            )

        cls.enfermedad = articulo("T-14", "14", "Enfermedad común", "Enfermedad común")
        cls.particulares = articulo("T-20", "20", "Razones particulares", "Razones particulares")
        cls.enfermedad_sup = articulo(
            "S-14", "14", "Enfermedad común", "Enfermedad común", "Suplente"
        )

    def marcar(self, designacion, fecha, codigo, horas="1", **extra):
        return RegistroAsistencia.objects.create(
            designacion=designacion, fecha=fecha,
            marca=MarcaAsistencia.objects.get(codigo=codigo),
            horas_inasistidas=Decimal(horas), **extra,
        )

    def renglones(self, anio=2026, mes=10):
        return list(
            RenglonMensual.objects.filter(anio=anio, mes=mes)
            .order_by("designacion__persona__apellido_nombre", "desde", "designacion_id")
        )

    def licencia_de_zarate(self):
        """El ejemplo del documento: LIC del 21 al 23/10 en todas sus materias."""
        self.marcar(self.m1, date(2026, 10, 21), "LIC", "2")
        self.marcar(self.m1, date(2026, 10, 22), "LIC", "3")
        self.marcar(self.m2, date(2026, 10, 22), "LIC", "4")
        self.marcar(self.m2, date(2026, 10, 23), "LIC", "2")


class DesgloseTests(BasePlanillaMensual):
    def test_un_renglon_por_cada_materia_con_el_mismo_desde_hasta(self):
        """RF-12, RF-13, RF-14 y RN-10 con el ejemplo del documento."""
        self.licencia_de_zarate()
        procesar_mes(2026, 10, self.usuario)

        self.assertEqual(
            [(r.designacion_id, r.marca, r.desde, r.hasta, r.dias, r.horas) for r in self.renglones()],
            [
                (self.m1.pk, "LIC", date(2026, 10, 21), date(2026, 10, 23), 2, Decimal("5")),
                (self.m2.pk, "LIC", date(2026, 10, 21), date(2026, 10, 23), 2, Decimal("6")),
            ],
        )

    def test_el_desglose_no_depende_de_que_se_haya_cargado_cada_materia(self):
        """RF-12: «no existen excepciones». Se cargó la novedad solo en Materia 1."""
        self.marcar(self.m1, date(2026, 10, 22), "LIC", "3")
        procesar_mes(2026, 10, self.usuario)

        self.assertEqual(
            [(r.designacion_id, r.horas) for r in self.renglones()],
            [(self.m1.pk, Decimal("3")), (self.m2.pk, Decimal("4"))],
        )

    def test_una_sola_jornada_tiene_desde_igual_a_hasta(self):
        self.marcar(self.m3, date(2026, 10, 22), "P", "2", observaciones="Trámite")
        procesar_mes(2026, 10, self.usuario)

        (renglon,) = self.renglones()
        self.assertEqual(renglon.desde, renglon.hasta)
        self.assertEqual(renglon.desde, date(2026, 10, 22))
        self.assertEqual(renglon.horas, Decimal("2"))

    def test_las_horas_salen_del_horario_y_no_de_lo_escrito_en_la_diaria(self):
        self.marcar(self.m3, date(2026, 10, 22), "LIC", "9")
        procesar_mes(2026, 10, self.usuario)
        self.assertEqual(self.renglones()[0].horas, Decimal("2"))

    def test_un_dia_presente_corta_el_periodo(self):
        self.marcar(self.m1, date(2026, 10, 21), "LIC", "2")
        self.marcar(self.m1, date(2026, 10, 22), "PR", "0")
        self.marcar(self.m2, date(2026, 10, 22), "PR", "0")
        self.marcar(self.m2, date(2026, 10, 23), "LIC", "2")
        procesar_mes(2026, 10, self.usuario)

        self.assertEqual(
            [(r.designacion_id, r.desde, r.hasta) for r in self.renglones()],
            [
                (self.m1.pk, date(2026, 10, 21), date(2026, 10, 21)),
                (self.m2.pk, date(2026, 10, 23), date(2026, 10, 23)),
            ],
        )

    def test_el_fin_de_semana_no_corta_el_periodo(self):
        # Viernes 23 y miércoles 28: entre medio ZARATE no dicta (sáb, dom, lun, mar).
        self.marcar(self.m2, date(2026, 10, 23), "LIC", "2")
        self.marcar(self.m1, date(2026, 10, 28), "LIC", "2")
        procesar_mes(2026, 10, self.usuario)

        self.assertEqual(
            {(r.desde, r.hasta) for r in self.renglones()},
            {(date(2026, 10, 23), date(2026, 10, 28))},
        )

    def test_un_periodo_que_cruza_de_mes_muestra_el_intervalo_completo(self):
        """RF-14: Desde y Hasta son los del período; días y horas, los del mes."""
        for fecha, horas in ((date(2026, 10, 28), "2"), (date(2026, 10, 29), "3"),
                             (date(2026, 11, 4), "2"), (date(2026, 11, 5), "3")):
            self.marcar(self.m1, fecha, "LIC", horas)
        for fecha, horas in ((date(2026, 10, 29), "4"), (date(2026, 10, 30), "2"),
                             (date(2026, 11, 5), "4")):
            self.marcar(self.m2, fecha, "LIC", horas)

        procesar_mes(2026, 10, self.usuario)
        procesar_mes(2026, 11, self.usuario)

        octubre = self.renglones(2026, 10)
        noviembre = self.renglones(2026, 11)
        for renglon in octubre + noviembre:
            self.assertEqual((renglon.desde, renglon.hasta), (date(2026, 10, 28), date(2026, 11, 5)))
        self.assertEqual([r.horas for r in octubre], [Decimal("5"), Decimal("6")])
        self.assertEqual([r.horas for r in noviembre], [Decimal("5"), Decimal("4")])

    def test_cada_inasistencia_injustificada_se_computa_por_su_dia(self):
        """RN-06: la falta simple vale solo por el día en que ocurrió."""
        self.marcar(self.m1, date(2026, 10, 21), "I", "2", estado_justificacion="INJUSTIFICADA")
        self.marcar(self.m1, date(2026, 10, 22), "I", "3", estado_justificacion="INJUSTIFICADA")
        self.marcar(self.m2, date(2026, 10, 22), "I", "4", estado_justificacion="INJUSTIFICADA")
        procesar_mes(2026, 10, self.usuario)

        self.assertEqual(
            [(r.designacion_id, r.desde, r.hasta) for r in self.renglones()],
            [
                (self.m1.pk, date(2026, 10, 21), date(2026, 10, 21)),
                (self.m1.pk, date(2026, 10, 22), date(2026, 10, 22)),
                (self.m2.pk, date(2026, 10, 22), date(2026, 10, 22)),
            ],
        )

    def test_un_mes_sin_novedades_no_genera_renglones(self):
        self.marcar(self.m1, date(2026, 10, 21), "PR", "0")
        resumen = procesar_mes(2026, 10, self.usuario)
        self.assertEqual(resumen["creados"], 0)
        self.assertEqual(self.renglones(), [])


class CuadrosYArticulosTests(BasePlanillaMensual):
    def test_inasistencias_y_permisos_van_a_il02(self):
        """RN-05."""
        self.marcar(self.m3, date(2026, 10, 22), "I", "2", estado_justificacion="INJUSTIFICADA")
        self.marcar(self.m1, date(2026, 10, 21), "P", "2", observaciones="Trámite")
        procesar_mes(2026, 10, self.usuario)
        self.assertEqual({r.planilla for r in self.renglones()}, {"IL-02"})

    def test_el_largo_tratamiento_va_a_il01(self):
        """RN-04."""
        self.marcar(self.m3, date(2026, 10, 22), "LT", "2")
        procesar_mes(2026, 10, self.usuario)
        self.assertEqual(self.renglones()[0].planilla, "IL-01")

    def test_una_licencia_sin_articulo_queda_pendiente_de_imputar(self):
        self.licencia_de_zarate()
        procesar_mes(2026, 10, self.usuario)
        self.assertEqual({r.planilla for r in self.renglones()}, {""})
        pendientes = cuadros_del_mes(2026, 10)[2]
        self.assertEqual(pendientes["planilla"], "PENDIENTE")
        self.assertEqual(len(pendientes["filas"]), 2)

    def test_al_elegir_el_articulo_se_autocompleta_el_codigo_y_se_deriva_el_cuadro(self):
        """RF-15."""
        self.licencia_de_zarate()
        procesar_mes(2026, 10, self.usuario)
        primero, segundo = self.renglones()

        imputar_renglones(
            2026, 10,
            {primero.pk: {"articulo": self.enfermedad.pk}, segundo.pk: {"articulo": self.particulares.pk}},
            self.usuario,
        )
        primero.refresh_from_db()
        segundo.refresh_from_db()

        self.assertEqual((primero.cod_licencia, primero.planilla), ("T-14", "IL-01"))
        self.assertEqual((segundo.cod_licencia, segundo.planilla), ("T-20", "IL-02"))
        self.assertEqual(primero.actualizado_por, self.usuario)

    def test_el_articulo_vale_para_las_otras_materias_del_mismo_periodo(self):
        self.licencia_de_zarate()
        procesar_mes(2026, 10, self.usuario)
        primero, segundo = self.renglones()

        imputar_renglones(2026, 10, {primero.pk: {"articulo": self.enfermedad.pk}}, self.usuario)

        segundo.refresh_from_db()
        self.assertEqual(segundo.articulo, self.enfermedad)
        self.assertEqual(segundo.planilla, "IL-01")

    def test_no_se_acepta_un_articulo_de_otra_situacion_de_revista(self):
        self.licencia_de_zarate()
        procesar_mes(2026, 10, self.usuario)
        with self.assertRaises(ValidationError):
            imputar_renglones(
                2026, 10, {self.renglones()[0].pk: {"articulo": self.enfermedad_sup.pk}},
            )

    def test_una_inasistencia_sin_formulario_no_admite_articulo(self):
        """RF-09: primero se recibe el formulario, después se imputa."""
        self.marcar(self.m3, date(2026, 10, 22), "I", "2", estado_justificacion="INJUSTIFICADA")
        procesar_mes(2026, 10, self.usuario)
        renglon = self.renglones()[0]

        with self.assertRaises(ValidationError):
            imputar_renglones(2026, 10, {renglon.pk: {"articulo": self.enfermedad.pk}})
        renglon.refresh_from_db()
        self.assertIsNone(renglon.articulo)

    def test_una_inasistencia_con_formulario_si_admite_articulo(self):
        self.marcar(
            self.m3, date(2026, 10, 22), "I", "2",
            estado_justificacion="JUSTIFICADA", nro_formulario="F-5",
            fecha_recepcion=date(2026, 10, 23),
        )
        procesar_mes(2026, 10, self.usuario)
        renglon = self.renglones()[0]

        imputar_renglones(2026, 10, {renglon.pk: {"articulo": self.enfermedad.pk}})
        renglon.refresh_from_db()
        self.assertEqual(renglon.cod_licencia, "T-14")

    def test_el_articulo_no_se_propaga_a_una_inasistencia_sin_formulario(self):
        # El mismo día: Materia 1 con licencia y Materia 2 con falta sin formulario.
        self.marcar(self.m1, date(2026, 10, 22), "LIC", "3")
        self.marcar(self.m2, date(2026, 10, 22), "I", "4", estado_justificacion="INJUSTIFICADA")
        procesar_mes(2026, 10, self.usuario)
        licencia = RenglonMensual.objects.get(designacion=self.m1)

        imputar_renglones(2026, 10, {licencia.pk: {"articulo": self.enfermedad.pk}})

        self.assertIsNone(RenglonMensual.objects.get(designacion=self.m2).articulo)

    def test_quitar_el_articulo_de_una_inasistencia_sin_formulario_se_permite(self):
        """Para poder corregir un renglón que quedó con artículo por error."""
        self.marcar(self.m3, date(2026, 10, 22), "I", "2", estado_justificacion="INJUSTIFICADA")
        procesar_mes(2026, 10, self.usuario)
        renglon = self.renglones()[0]
        RenglonMensual.objects.filter(pk=renglon.pk).update(articulo=self.enfermedad)

        imputar_renglones(2026, 10, {renglon.pk: {"articulo": ""}})
        renglon.refresh_from_db()
        self.assertIsNone(renglon.articulo)
        self.assertEqual(renglon.planilla, "IL-02")

    def test_oficina_y_anio_nacen_precargados(self):
        """RN-07 y RN-08."""
        self.licencia_de_zarate()
        procesar_mes(2026, 10, self.usuario)
        for renglon in self.renglones():
            self.assertEqual(renglon.oficina, "1452")
            self.assertEqual(renglon.anio_planilla, 2026)

    def test_la_oficina_sale_de_los_parametros_del_sistema(self):
        from reportes.models import ParametroSistema

        parametros = ParametroSistema.obtener()
        parametros.codigo_oficina = "9999"
        parametros.save()
        self.licencia_de_zarate()
        procesar_mes(2026, 10, self.usuario)
        self.assertEqual({r.oficina for r in self.renglones()}, {"9999"})

    def test_volver_a_procesar_conserva_lo_imputado(self):
        self.licencia_de_zarate()
        procesar_mes(2026, 10, self.usuario)
        renglon = self.renglones()[0]
        imputar_renglones(
            2026, 10,
            {renglon.pk: {"articulo": self.enfermedad.pk, "resolucion": "Res. 123/2026"}},
        )

        resumen = procesar_mes(2026, 10, self.usuario)

        self.assertEqual(resumen, {"creados": 0, "actualizados": 2, "eliminados": 0, "desactualizados": 0})
        renglon.refresh_from_db()
        self.assertEqual(renglon.articulo, self.enfermedad)
        self.assertEqual(renglon.resolucion, "Res. 123/2026")

    def test_si_el_periodo_se_alarga_se_conserva_el_articulo(self):
        self.marcar(self.m1, date(2026, 10, 21), "LIC", "2")
        procesar_mes(2026, 10, self.usuario)
        imputar_renglones(2026, 10, {self.renglones()[0].pk: {"articulo": self.enfermedad.pk}})

        self.marcar(self.m1, date(2026, 10, 22), "LIC", "3")
        procesar_mes(2026, 10, self.usuario)

        de_m1 = RenglonMensual.objects.get(designacion=self.m1)
        self.assertEqual((de_m1.desde, de_m1.hasta), (date(2026, 10, 21), date(2026, 10, 22)))
        self.assertEqual(de_m1.articulo, self.enfermedad)

    def test_si_se_corrige_la_diaria_el_renglon_desaparece(self):
        registro = self.marcar(self.m3, date(2026, 10, 22), "LIC", "2")
        procesar_mes(2026, 10, self.usuario)
        registro.marca = MarcaAsistencia.objects.get(codigo="PR")
        registro.save()

        resumen = procesar_mes(2026, 10, self.usuario)
        self.assertEqual(resumen["eliminados"], 1)
        self.assertEqual(self.renglones(), [])

    def test_una_licencia_ya_otorgada_trae_su_articulo(self):
        licencia = LicenciaOtorgada.objects.create(
            designacion=self.m3, articulo=self.enfermedad, sit_rev="Titular",
            desde=date(2026, 10, 22), hasta=date(2026, 10, 22), nro_formulario="F-9",
        )
        self.marcar(self.m3, date(2026, 10, 22), "LIC", "2", licencia=licencia)
        procesar_mes(2026, 10, self.usuario)

        (renglon,) = self.renglones()
        self.assertEqual((renglon.cod_licencia, renglon.planilla), ("T-14", "IL-01"))
        self.assertEqual(renglon.nro_formulario, "F-9")


class DisposicionesTests(BasePlanillaMensual):
    def preparar(self):
        self.licencia_de_zarate()
        self.marcar(self.m3, date(2026, 10, 22), "P", "2", observaciones="Trámite")
        procesar_mes(2026, 10, self.usuario)

    def test_una_disposicion_por_agente_y_periodo_en_orden_alfabetico(self):
        """RF-16 y RN-11."""
        self.preparar()
        emitidas = emitir_disposiciones_planilla(2026, 10, self.usuario)

        self.assertEqual([numero for numero, _ in emitidas], [1, 2])
        self.assertEqual(
            [(r.designacion.persona.apellido_nombre, r.disp_numero) for r in self.renglones()],
            [("Abel, Luis", "1"), ("Zárate, Ana", "2"), ("Zárate, Ana", "2")],
        )
        for renglon in self.renglones():
            self.assertEqual(renglon.disp_tipo, "Disposición")
            self.assertEqual(renglon.disp_anio, 2026)
            self.assertEqual(renglon.oficina, "1452")

    def test_la_numeracion_continua_la_del_anio(self):
        LicenciaOtorgada.objects.create(
            designacion=self.m3, articulo=self.enfermedad, sit_rev="Titular",
            desde=date(2026, 9, 1), hasta=date(2026, 9, 1),
            disp_tipo="Disposición", disp_oficina="1452", disp_numero="7", disp_anio=2026,
        )
        self.preparar()
        emitidas = emitir_disposiciones_planilla(2026, 10, self.usuario)
        self.assertEqual([numero for numero, _ in emitidas], [8, 9])

    def test_emitir_dos_veces_no_vuelve_a_numerar(self):
        self.preparar()
        emitir_disposiciones_planilla(2026, 10, self.usuario)
        self.assertEqual(emitir_disposiciones_planilla(2026, 10, self.usuario), [])

    def test_la_inasistencia_sin_formulario_no_lleva_disposicion(self):
        self.marcar(self.m3, date(2026, 10, 22), "I", "2", estado_justificacion="INJUSTIFICADA")
        procesar_mes(2026, 10, self.usuario)
        self.assertEqual(emitir_disposiciones_planilla(2026, 10, self.usuario), [])

    def test_un_renglon_con_disposicion_no_se_borra_solo(self):
        registro = self.marcar(self.m3, date(2026, 10, 22), "LIC", "2")
        procesar_mes(2026, 10, self.usuario)
        emitir_disposiciones_planilla(2026, 10, self.usuario)
        registro.marca = MarcaAsistencia.objects.get(codigo="PR")
        registro.save()

        resumen = procesar_mes(2026, 10, self.usuario)
        self.assertEqual(resumen["desactualizados"], 1)
        self.assertTrue(self.renglones()[0].desactualizado)


class PantallaTests(BasePlanillaMensual):
    def setUp(self):
        self.client.force_login(self.usuario)
        self.url = reverse("licencias:planilla_mensual", args=[2026, 10])

    def test_el_circuito_completo_desde_la_pantalla(self):
        self.licencia_de_zarate()

        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, "Procesar el mes")

        self.client.post(self.url, {"accion": "procesar"})
        primero, segundo = self.renglones()
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, "Pendientes de imputar")
        self.assertContains(respuesta, 'data-cod="T-14"')          # RF-15
        self.assertContains(respuesta, f'name="oficina-{primero.pk}" value="1452"')   # RN-07
        self.assertContains(respuesta, f'name="anio-{primero.pk}" value="2026"')      # RN-08

        self.client.post(
            self.url,
            {
                "accion": "guardar",
                f"articulo-{primero.pk}": self.enfermedad.pk,
                f"articulo-{segundo.pk}": "",
                f"resolucion-{primero.pk}": "Res. 55/2026",
                f"oficina-{primero.pk}": "",
                f"anio-{primero.pk}": "",
            },
        )
        primero.refresh_from_db()
        segundo.refresh_from_db()
        self.assertEqual((primero.cod_licencia, primero.planilla), ("T-14", "IL-01"))
        self.assertEqual(segundo.planilla, "IL-01")
        self.assertEqual(primero.resolucion, "Res. 55/2026")
        self.assertEqual((primero.oficina, primero.anio_planilla), ("1452", 2026))

        self.client.post(self.url, {"accion": "emitir"})
        self.assertEqual({r.disp_numero for r in self.renglones()}, {"1"})

        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, "Cuadro IL-01")
        self.assertContains(respuesta, "1/2026")

    def test_el_procesamiento_queda_en_la_bitacora(self):
        """RF-20."""
        self.licencia_de_zarate()
        self.client.post(self.url, {"accion": "procesar"})
        evento = EventoAsistencia.objects.get(accion="PLANILLA_MENSUAL")
        self.assertEqual(evento.usuario, self.usuario)
        self.assertEqual(evento.despues["creados"], 2)
        for renglon in self.renglones():
            self.assertEqual(renglon.creado_por, self.usuario)
            self.assertIsNotNone(renglon.creado_en)

    def test_las_disposiciones_emitidas_se_ven_agrupadas(self):
        """RN-11: después de emitir se ve cada disposición con sus materias."""
        self.licencia_de_zarate()
        self.client.post(self.url, {"accion": "procesar"})
        self.client.post(self.url, {"accion": "emitir"})

        respuesta = self.client.get(self.url)
        (disposicion,) = respuesta.context["emitidas"]
        self.assertEqual((disposicion["numero"], disposicion["anio"]), ("1", 2026))
        self.assertEqual(
            [r.designacion_id for r in disposicion["renglones"]],
            [self.m1.pk, self.m2.pk],
        )
        self.assertContains(respuesta, "Disposiciones del mes")
        self.assertContains(respuesta, "Materia 1")
        self.assertContains(respuesta, "Materia 2")

    def test_sin_emitir_no_hay_disposiciones_del_mes(self):
        self.licencia_de_zarate()
        self.client.post(self.url, {"accion": "procesar"})
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.context["emitidas"], [])
        self.assertContains(respuesta, "Todavía no hay disposiciones emitidas")

    def test_las_faltas_sin_formulario_aparecen_en_el_cuadro_rojo(self):
        # ZARATE falta el jueves 22 en sus dos materias, sin papel.
        self.marcar(self.m1, date(2026, 10, 22), "I", "3", estado_justificacion="INJUSTIFICADA")
        self.marcar(self.m2, date(2026, 10, 22), "I", "4", estado_justificacion="INJUSTIFICADA")
        self.client.post(self.url, {"accion": "procesar"})

        respuesta = self.client.get(self.url)
        (falta,) = respuesta.context["sin_formulario"]   # una fila por docente y día
        self.assertEqual(falta["fecha"], date(2026, 10, 22))
        self.assertEqual(len(falta["renglones"]), 2)
        self.assertContains(respuesta, "Faltas sin formulario (1)")
        self.assertContains(
            respuesta,
            reverse("asistencia:recepcionar_formulario", args=[falta["registro"].pk]),
        )
        self.assertContains(respuesta, f"?designacion={self.m1.pk}&amp;desde=2026-10-22")
        self.assertContains(respuesta, f"?designacion={self.m2.pk}&amp;desde=2026-10-22")

    def test_recibir_el_formulario_desde_el_cuadro_rojo_vuelve_a_la_planilla(self):
        from asistencias.services import adquirir_sesion_edicion  # noqa: F401
        registro = self.marcar(self.m3, date(2026, 10, 22), "I", "2", estado_justificacion="INJUSTIFICADA")
        self.client.post(self.url, {"accion": "procesar"})
        self.usuario.user_permissions.add(
            Permission.objects.get(codename="recepcionar_formulario"),
            Permission.objects.get(codename="view_registroasistencia"),
        )

        respuesta = self.client.post(
            reverse("asistencia:recepcionar_formulario", args=[registro.pk]),
            {
                "estado_justificacion": "JUSTIFICADA",
                "nro_formulario": "F-9",
                "fecha_recepcion": "2026-10-23",
                "nueva_marca": "P",
                "motivo": "",
                "volver": self.url,
            },
        )
        self.assertRedirects(respuesta, self.url, fetch_redirect_response=False)

        self.client.post(self.url, {"accion": "procesar"})
        self.assertEqual(self.client.get(self.url).context["sin_formulario"], [])
        self.assertEqual(self.renglones()[0].marca, "P")

    def test_nueva_licencia_se_abre_precargada_y_vuelve_a_la_planilla(self):
        self.usuario.user_permissions.add(Permission.objects.get(codename="add_licenciaotorgada"))
        url = reverse("licencias:nueva_licencia_otorgada")

        respuesta = self.client.get(
            url, {"designacion": self.m3.pk, "desde": "2026-10-22", "volver": self.url}
        )
        form = respuesta.context["form"]
        self.assertEqual(form.initial["designacion"], self.m3.pk)
        self.assertEqual(form.initial["desde"], date(2026, 10, 22))
        self.assertContains(respuesta, f'name="volver" value="{self.url}"')

    def test_volver_no_acepta_direcciones_de_otro_sitio(self):
        from licencias.views import _volver_seguro
        from django.test import RequestFactory

        pedido = RequestFactory().get("/", {"volver": "https://otro-sitio.com/robar"})
        self.assertEqual(_volver_seguro(pedido), "")

    def test_quien_solo_consulta_no_puede_procesar(self):
        lector = get_user_model().objects.create_user("lector", password="x")
        lector.user_permissions.add(Permission.objects.get(codename="view_licenciaotorgada"))
        self.client.force_login(lector)
        self.licencia_de_zarate()

        self.client.post(self.url, {"accion": "procesar"})
        self.assertEqual(self.renglones(), [])
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_sin_permiso_no_se_entra(self):
        self.client.force_login(get_user_model().objects.create_user("nadie", password="x"))
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_exporta_los_cuadros_en_csv(self):
        self.licencia_de_zarate()
        self.client.post(self.url, {"accion": "procesar"})
        respuesta = self.client.get(reverse("licencias:planilla_mensual_csv", args=[2026, 10]))
        contenido = respuesta.content.decode("utf-8")
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("Cód. licencia", contenido)
        self.assertIn("Materia 2", contenido)
        self.assertIn("21/10/2026;23/10/2026", contenido)

    def test_un_mes_invalido_da_404(self):
        self.assertEqual(
            self.client.get(reverse("licencias:planilla_mensual", args=[2026, 13])).status_code, 404
        )


class ArticuloHeredadoTests(BasePlanillaMensual):
    """
    Un renglón que trae el artículo de su licencia otorgada no debe frenar el
    guardado de la planilla aunque no coincida la situación de revista: solo se
    controla el artículo que el operador cambia en la pantalla.
    """

    def setUp(self):
        self.interina = Designacion.objects.create(
            persona=self.abel, cargo=self.cargo, situacion_revista="INT",
            desde=date(2026, 3, 1),
        )
        Horario.objects.create(designacion=self.interina, dia="LUN", horas_catedra=4)
        licencia = LicenciaOtorgada.objects.create(
            designacion=self.interina, articulo=self.enfermedad, sit_rev="Interino",
            desde=date(2026, 10, 5), hasta=date(2026, 10, 5),
        )
        self.marcar(self.interina, date(2026, 10, 5), "LIC", "4", licencia=licencia)
        self.licencia_de_zarate()
        procesar_mes(2026, 10, self.usuario)

    def test_un_renglon_sin_tocar_no_frena_el_guardado(self):
        heredado = RenglonMensual.objects.get(designacion=self.interina)
        de_zarate = RenglonMensual.objects.filter(designacion=self.m1).get()

        imputar_renglones(
            2026, 10,
            {
                heredado.pk: {"articulo": self.enfermedad.pk},   # sin cambios
                de_zarate.pk: {"articulo": self.enfermedad.pk},  # elegido ahora
            },
            self.usuario,
        )

        de_zarate.refresh_from_db()
        heredado.refresh_from_db()
        self.assertEqual(de_zarate.cod_licencia, "T-14")
        self.assertEqual(heredado.articulo, self.enfermedad)

    def test_elegir_a_mano_un_articulo_de_otra_situacion_sigue_rechazado(self):
        heredado = RenglonMensual.objects.get(designacion=self.interina)

        with self.assertRaises(ValidationError):
            imputar_renglones(
                2026, 10, {heredado.pk: {"articulo": self.particulares.pk}},
            )
