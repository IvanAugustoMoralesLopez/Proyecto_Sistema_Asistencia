"""
Planilla mensual de asistencia (pestaña «Mes» de Asistencia del día): una
fila por docente, una columna por día, filtro por carrera y totales.
"""

from datetime import date

from django.contrib.messages import get_messages
from django.urls import reverse

from personal.models import Carrera, Designacion, EspacioCurricular, Horario, Persona

from .models import DiaNoLaborable, MarcaAsistencia, RegistroAsistencia
from .services import SIN_CARRERA, mes_pedido, mes_vecino, planilla_del_mes
from .tests import LUNES, BaseAsistenciaTests, crear_usuario

# Septiembre de 2026: el 14 y el 21 son lunes, el 12 es sábado.
FIN_DE_MES = date(2026, 9, 30)


def celda(fila, fecha):
    return fila["celdas"][fecha.day - 1]


class PlanillaMesBase(BaseAsistenciaTests):
    """Un docente con dos materias en carreras distintas, las dos los lunes."""

    def setUp(self):
        super().setUp()
        self.software = Carrera.objects.create(nombre="Desarrollo de Software")
        self.higiene = Carrera.objects.create(nombre="Higiene y Seguridad")
        self.programacion = EspacioCurricular.objects.create(nombre="Programación I")
        self.programacion.carreras.add(self.software)
        self.legislacion = EspacioCurricular.objects.create(nombre="Legislación")
        self.legislacion.carreras.add(self.higiene)

        self.docente = Persona.objects.create(
            dni="27111222", apellido_nombre="GÓMEZ, LUCÍA", sexo="F"
        )
        self.en_software = self.designar(self.programacion, self.software)
        self.en_higiene = self.designar(self.legislacion, self.higiene)
        self.marca_lt = MarcaAsistencia.objects.get(codigo="LT")

    def designar(self, materia, carrera, persona=None, dia="LUN"):
        designacion = Designacion.objects.create(
            persona=persona or self.docente,
            cargo=self.cargo,
            espacio_curricular=materia,
            carrera=carrera,
            desde=date(2026, 3, 1),
        )
        Horario.objects.create(designacion=designacion, dia=dia, horas_catedra=2)
        return designacion

    def marcar(self, designacion, fecha, marca, licencia=None):
        return RegistroAsistencia.objects.create(
            designacion=designacion, fecha=fecha, marca=marca, licencia=licencia
        )

    def fila_de(self, planilla, persona=None):
        persona = persona or self.docente
        return next(f for f in planilla["filas"] if f["persona"].pk == persona.pk)


class PlanillaDelMesTests(PlanillaMesBase):
    def test_una_fila_por_docente_con_la_marca_de_mas_peso(self):
        self.marcar(self.en_software, LUNES, self.marca_i)
        self.marcar(self.en_higiene, LUNES, self.marca_presente)

        planilla = planilla_del_mes(2026, 9, hoy=FIN_DE_MES)
        filas = [f for f in planilla["filas"] if f["persona"].pk == self.docente.pk]
        self.assertEqual(len(filas), 1)

        dia = celda(filas[0], LUNES)
        self.assertEqual(dia["texto"], "I")
        self.assertTrue(dia["mixta"])
        self.assertIn("Programación I", dia["detalle"])
        self.assertIn("Legislación", dia["detalle"])
        # El día cuenta en las dos columnas: faltó a una materia y asistió a la otra.
        self.assertEqual(filas[0]["totales"]["faltas"], 1)
        self.assertEqual(filas[0]["totales"]["presentes"], 1)

    def test_presente_se_ve_como_pr_y_se_cuenta(self):
        self.marcar(self.en_software, LUNES, self.marca_presente)
        self.marcar(self.en_higiene, LUNES, self.marca_presente)
        self.marcar(self.en_software, date(2026, 9, 21), self.marca_presente)

        fila = self.fila_de(planilla_del_mes(2026, 9, hoy=FIN_DE_MES))
        dia = celda(fila, LUNES)
        self.assertEqual(dia["texto"], "PR")
        self.assertEqual(dia["clase"], "pr")
        self.assertFalse(dia["mixta"])
        # Cuenta días, no materias: el lunes 14 con dos materias es un día.
        self.assertEqual(fila["totales"]["presentes"], 2)
        self.assertEqual(fila["totales_en_orden"][0], 2)

    def test_el_permiso_se_ve_como_p(self):
        self.marcar(self.en_software, LUNES, self.marca_permiso)
        self.marcar(self.en_higiene, LUNES, self.marca_presente)

        fila = self.fila_de(planilla_del_mes(2026, 9, hoy=FIN_DE_MES))
        self.assertEqual(celda(fila, LUNES)["texto"], "P")
        self.assertEqual(fila["totales"]["permisos"], 1)

    def test_la_licencia_pesa_mas_que_la_falta(self):
        self.marcar(self.en_software, LUNES, self.marca_i)
        self.marcar(self.en_higiene, LUNES, self.marca_lic)

        fila = self.fila_de(planilla_del_mes(2026, 9, hoy=FIN_DE_MES))
        self.assertEqual(celda(fila, LUNES)["texto"], "LIC")
        # El día cuenta en las dos columnas: faltó a una materia y estuvo de
        # licencia en la otra.
        self.assertEqual(fila["totales"]["faltas"], 1)
        self.assertEqual(fila["totales"]["licencia"], 1)

    def test_filtrar_por_carrera_usa_solo_sus_materias(self):
        self.marcar(self.en_software, LUNES, self.marca_i)
        self.marcar(self.en_higiene, LUNES, self.marca_presente)

        en_higiene = self.fila_de(planilla_del_mes(2026, 9, self.higiene, hoy=FIN_DE_MES))
        self.assertEqual(celda(en_higiene, LUNES)["texto"], "PR")
        self.assertEqual(en_higiene["totales"]["faltas"], 0)

        en_software = self.fila_de(planilla_del_mes(2026, 9, self.software, hoy=FIN_DE_MES))
        self.assertEqual(celda(en_software, LUNES)["texto"], "I")

    def test_sin_carrera_muestra_las_designaciones_sin_carrera(self):
        planilla = planilla_del_mes(2026, 9, SIN_CARRERA, hoy=FIN_DE_MES)
        personas = {f["persona"].pk for f in planilla["filas"]}
        # La designación base (PEREZ) no tiene carrera; la docente de prueba sí.
        self.assertEqual(personas, {self.persona.pk})

    def test_dia_con_clase_sin_cargar_hasta_hoy(self):
        self.marcar(self.en_software, LUNES, self.marca_presente)
        self.marcar(self.en_higiene, LUNES, self.marca_presente)
        lunes_21 = date(2026, 9, 21)
        lunes_28 = date(2026, 9, 28)

        fila = self.fila_de(planilla_del_mes(2026, 9, hoy=date(2026, 9, 22)))
        self.assertEqual(celda(fila, lunes_21)["texto"], "·")
        self.assertEqual(celda(fila, lunes_21)["clase"], "pend")
        # Un día que todavía no llegó no se marca como pendiente.
        self.assertEqual(celda(fila, lunes_28)["texto"], "")
        # Un martes no tiene clase.
        self.assertEqual(celda(fila, date(2026, 9, 22))["texto"], "")

    def test_feriado_y_fin_de_semana_en_gris_sin_pendientes(self):
        lunes_21 = date(2026, 9, 21)
        DiaNoLaborable.objects.create(fecha=lunes_21, tipo="FERIADO", descripcion="Prueba")

        planilla = planilla_del_mes(2026, 9, hoy=FIN_DE_MES)
        fila = self.fila_de(planilla)
        self.assertTrue(celda(fila, lunes_21)["gris"])
        self.assertEqual(celda(fila, lunes_21)["texto"], "")
        self.assertTrue(celda(fila, date(2026, 9, 12))["gris"])
        self.assertEqual(planilla["dias"][20]["motivo"], "Feriado: Prueba")

    def test_licencias_repartidas_por_categoria(self):
        enfermedad = self.crear_licencia(
            desde=date(2026, 9, 7), hasta=date(2026, 9, 7), designacion=self.en_software
        )
        self.marcar(self.en_software, date(2026, 9, 7), self.marca_lic, licencia=enfermedad)
        self.marcar(self.en_software, LUNES, self.marca_lt)
        # LIC todavía sin licencia ni artículo: solo cuenta en «Licencia».
        self.marcar(self.en_software, date(2026, 9, 21), self.marca_lic)

        totales = self.fila_de(planilla_del_mes(2026, 9, hoy=FIN_DE_MES))["totales"]
        self.assertEqual(totales["licencia"], 3)
        self.assertEqual(totales["enf_comun"], 1)
        self.assertEqual(totales["largo_trat"], 1)
        self.assertEqual(totales["otros"], 0)

    def test_orden_alfabetico_sin_importar_acentos(self):
        alvarez = Persona.objects.create(dni="20111222", apellido_nombre="ÁLVAREZ, ANA", sexo="F")
        self.designar(self.programacion, self.software, persona=alvarez)

        planilla = planilla_del_mes(2026, 9, hoy=FIN_DE_MES)
        nombres = [f["persona"].apellido_nombre for f in planilla["filas"]]
        self.assertEqual(nombres, ["ÁLVAREZ, ANA", "GÓMEZ, LUCÍA", "PEREZ, JUAN"])
        self.assertEqual([f["numero"] for f in planilla["filas"]], [1, 2, 3])

    def test_designacion_vencida_no_aparece_si_no_tiene_registros(self):
        for designacion in (self.en_software, self.en_higiene):
            designacion.hasta = date(2026, 8, 31)
            designacion.save()

        planilla = planilla_del_mes(2026, 9, hoy=FIN_DE_MES)
        self.assertNotIn(self.docente.pk, {f["persona"].pk for f in planilla["filas"]})


class MesPedidoTests(PlanillaMesBase):
    def test_lee_el_valor_del_campo_mes(self):
        self.assertEqual(mes_pedido("2026-09", None), date(2026, 9, 1))
        self.assertEqual(mes_pedido("", date(2026, 1, 1)), date(2026, 1, 1))

    def test_rechaza_meses_invalidos(self):
        for texto in ("2026-13", "2026-00", "1999-05", "hola", "2026-9-1"):
            with self.subTest(texto=texto):
                self.assertIsNone(mes_pedido(texto, None))

    def test_mes_vecino_cruza_el_anio(self):
        self.assertEqual(mes_vecino(date(2026, 1, 1), -1), date(2025, 12, 1))
        self.assertEqual(mes_vecino(date(2026, 12, 1), 1), date(2027, 1, 1))
        self.assertIsNone(mes_vecino(date(2100, 12, 1), 1))


class PantallaPlanillaMesTests(PlanillaMesBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)
        self.url = reverse("asistencia:planilla_mes")

    def test_muestra_la_planilla_del_mes(self):
        self.marcar(self.en_software, LUNES, self.marca_i)

        respuesta = self.client.get(self.url, {"mes": "2026-09"})

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Asistencia de Septiembre 2026")
        self.assertContains(respuesta, "GÓMEZ, LUCÍA")
        self.assertContains(respuesta, 'id="planilla-mes"')
        self.assertContains(respuesta, "Desarrollo de Software")
        self.assertContains(respuesta, "ENF COMUN")

    def test_filtra_por_carrera(self):
        otra = Persona.objects.create(dni="20999888", apellido_nombre="SOLO HIGIENE", sexo="M")
        self.designar(self.legislacion, self.higiene, persona=otra)

        respuesta = self.client.get(
            self.url, {"mes": "2026-09", "carrera": self.software.pk}
        )

        self.assertContains(respuesta, "GÓMEZ, LUCÍA")
        self.assertNotContains(respuesta, "SOLO HIGIENE")

    def test_las_pestanas_conectan_dia_y_mes(self):
        dia = self.client.get(reverse("asistencia:registro_diario"), {"fecha": "2026-09-14"})
        self.assertContains(dia, f'{self.url}?mes=2026-09')

        mes = self.client.get(self.url, {"mes": "2026-09"})
        self.assertContains(mes, f'{reverse("asistencia:registro_diario")}?fecha=2026-09-01')

    def test_mes_invalido_vuelve_con_aviso(self):
        respuesta = self.client.get(self.url, {"mes": "2026-13"})
        self.assertEqual(respuesta.status_code, 302)
        mensajes = [str(m) for m in get_messages(respuesta.wsgi_request)]
        self.assertIn("El mes elegido no es válido.", mensajes)

    def test_carrera_inexistente_vuelve_al_mes(self):
        respuesta = self.client.get(self.url, {"mes": "2026-09", "carrera": "999999"})
        self.assertRedirects(respuesta, f"{self.url}?mes=2026-09", fetch_redirect_response=False)

    def test_exporta_csv(self):
        self.marcar(self.en_software, LUNES, self.marca_i)

        respuesta = self.client.get(
            reverse("asistencia:planilla_mes_csv"),
            {"mes": "2026-09", "carrera": self.software.pk},
        )

        self.assertEqual(respuesta["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn(
            'filename="asistencia_2026-09_desarrollo-de-software.csv"',
            respuesta["Content-Disposition"],
        )
        lineas = respuesta.content.decode("utf-8-sig").splitlines()
        self.assertTrue(lineas[1].startswith("N°;Apellido y nombre;DNI;1;2;"))
        self.assertTrue(
            lineas[1].endswith("Presentes;Faltas;Permisos;Licencia;ENF COMUN;LARGO TRAT;OTROS")
        )
        fila = lineas[2].split(";")
        self.assertEqual(fila[1], "GÓMEZ, LUCÍA")
        self.assertEqual(fila[3 + LUNES.day - 1], "I")

    def test_sin_permiso_no_entra(self):
        self.client.force_login(crear_usuario("sin_permisos"))
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("asistencia:planilla_mes_csv")).status_code, 403
        )
