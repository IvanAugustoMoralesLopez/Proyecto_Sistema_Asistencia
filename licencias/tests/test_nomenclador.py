"""Nomenclador oficial: carga del CSV, equivalencia por motivo y reemplazo de los artículos de prueba."""

from datetime import date
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from licencias.clasificacion import planilla_para_categoria
from licencias.models import LicenciaArticulo, LicenciaOtorgada
from licencias.nomenclador import (
    articulo_para,
    cargar_nomenclador,
    leer_nomenclador,
    motivo_de,
    motivos_para,
    reemplazar_inventados,
)
from personal.models import Cargo, Designacion, Persona


class LecturaTests(TestCase):
    def test_el_csv_del_repositorio_es_valido(self):
        filas = leer_nomenclador()
        self.assertEqual(len(filas), 148)
        codigos = {f["cod_licencia"] for f in filas}
        self.assertIn("1-1-1", codigos)
        self.assertIn("2-13-1", codigos)
        # Sanciones y movimientos quedan afuera.
        self.assertFalse(any(c.startswith(("4-", "5-")) for c in codigos))

    def test_agrupacion_1_va_al_il01_y_el_resto_al_il02(self):
        for fila in leer_nomenclador():
            esperado = "IL-01" if fila["cod_licencia"].startswith("1-") else "IL-02"
            self.assertEqual(
                planilla_para_categoria(fila["categoria_informe"]), esperado, fila["cod_licencia"]
            )

    def test_motivo_de(self):
        self.assertEqual(motivo_de("1-1-3"), "1-1")
        self.assertEqual(motivo_de("2-13-4"), "2-13")
        self.assertEqual(motivo_de("T-14"), "")


class CargaTests(TestCase):
    def test_carga_y_se_puede_repetir(self):
        salida = StringIO()
        call_command("cargar_nomenclador", stdout=salida)
        self.assertIn("148 nuevos", salida.getvalue())
        self.assertEqual(LicenciaArticulo.objects.filter(cod_licencia="1-1-1").get().articulo, "309 B 1")

        salida = StringIO()
        call_command("cargar_nomenclador", stdout=salida)
        self.assertIn("0 nuevos, 0 actualizados, 148 sin cambios", salida.getvalue())

    def test_dry_run_no_guarda(self):
        salida = StringIO()
        call_command("cargar_nomenclador", "--dry-run", stdout=salida)
        self.assertIn("[prueba] Nomenclador: 148 nuevos", salida.getvalue())
        self.assertFalse(LicenciaArticulo.objects.exists())

    def test_actualiza_lo_que_cambio(self):
        cargar_nomenclador(leer_nomenclador())
        LicenciaArticulo.objects.filter(cod_licencia="1-1-1").update(tope_dias_anual=10)
        resultado = cargar_nomenclador(leer_nomenclador())
        self.assertEqual(resultado.actualizados, ["1-1-1"])
        self.assertEqual(LicenciaArticulo.objects.get(cod_licencia="1-1-1").tope_dias_anual, 45)

    def test_un_csv_con_errores_no_carga_nada(self):
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as archivo:
            archivo.write(
                "codigo,agrupacion,motivo,articulo,sit_rev,goce_haberes,autoridad,plazo,tope_dias_anual,clase,categoria\n"
                "1-1-1,1,Enfermedad,309 B 1,Titular,Con goce,Director,45 días,45,Licencia,Enfermedad común\n"
                "9-9-9,9,Otra,1,Jefe,Con goce,Director,,,Licencia,Inventada\n"
            )
        with self.assertRaises(CommandError) as ctx:
            call_command("cargar_nomenclador", "--archivo", archivo.name, stdout=StringIO())
        self.assertIn("Fila 3", str(ctx.exception))
        self.assertFalse(LicenciaArticulo.objects.exists())


class EquivalenciaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cargar_nomenclador(leer_nomenclador())

    def art(self, codigo):
        return LicenciaArticulo.objects.get(cod_licencia=codigo)

    def test_mismo_motivo_otra_situacion(self):
        self.assertEqual(articulo_para(self.art("1-1-1"), "Interino").cod_licencia, "1-1-3")
        self.assertEqual(articulo_para(self.art("1-1-1"), "Suplente").cod_licencia, "1-1-4")
        self.assertEqual(articulo_para(self.art("1-1-3"), "Titular").cod_licencia, "1-1-1")

    def test_respeta_la_forma_de_pago(self):
        # 1-2-2 es largo tratamiento al 50 %: el interino al 50 % es 1-2-6.
        self.assertEqual(articulo_para(self.art("1-2-2"), "Interino").cod_licencia, "1-2-6")

    def test_sin_equivalente_devuelve_none(self):
        # Fuerza mayor (2-4) existe solo para titulares.
        self.assertIsNone(articulo_para(self.art("2-4-1"), "Interino"))

    def test_motivos_para_filtra_por_situacion(self):
        nombres = {
            m["motivo"] for _, motivos in motivos_para(["Interino"]) for m in motivos
        }
        self.assertIn("1-1", nombres)
        self.assertNotIn("2-4", nombres)  # solo titulares
        grupos = [g for g, _ in motivos_para(["Titular"])]
        self.assertEqual(grupos, ["Salud", "Otras licencias", "Permisos"])

    def test_con_cargos_mixtos_aparecen_los_de_cualquiera(self):
        motivos = {m["motivo"]: m for _, lista in motivos_para(["Interino", "Titular"]) for m in lista}
        self.assertIn("2-4", motivos)  # fuerza mayor: solo para su cargo titular
        # El representante es el de su primera situación, con goce.
        self.assertEqual(motivos["1-1"]["representante"].cod_licencia, "1-1-3")
        self.assertEqual(motivos["1-2"]["representante"].cod_licencia, "1-2-5")


class ReemplazoInventadosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cargo = Cargo.objects.create(codigo="HC", descripcion="Hora cátedra")
        persona = Persona.objects.create(dni="30111222", apellido_nombre="Zárate, Ana")
        cls.tit = Designacion.objects.create(
            persona=persona, cargo=cargo, situacion_revista="TIT", desde=date(2026, 3, 1),
        )
        cls.int_ = Designacion.objects.create(
            persona=persona, cargo=cargo, situacion_revista="INT", desde=date(2026, 3, 1),
        )

        def inventado(codigo, numero, tipo, categoria, situacion="Titular"):
            return LicenciaArticulo.objects.create(
                cod_licencia=codigo, articulo=numero, tipo_licencia=tipo,
                categoria_informe=categoria, sit_rev=situacion,
                goce_haberes="Con goce de haberes", autoridad="Dirección", plazo="-",
            )

        cls.t14 = inventado("T-14", "14", "Enfermedad común", "Enfermedad común")
        cls.t20 = inventado("T-20", "20", "Razones particulares", "Razones particulares")
        cls.lic_tit = LicenciaOtorgada.objects.create(
            designacion=cls.tit, articulo=cls.t14, sit_rev="Titular",
            desde=date(2026, 10, 5), hasta=date(2026, 10, 6),
        )
        cls.lic_particulares = LicenciaOtorgada.objects.create(
            designacion=cls.tit, articulo=cls.t20, sit_rev="Titular",
            desde=date(2026, 11, 2), hasta=date(2026, 11, 2),
        )
        cargar_nomenclador(leer_nomenclador())

    def test_vista_previa_no_cambia_nada(self):
        resultado = reemplazar_inventados(guardar=False)
        self.assertEqual(len(resultado.cambios), 2)
        self.assertEqual(sorted(resultado.borrados), ["T-14", "T-20"])
        self.lic_tit.refresh_from_db()
        self.assertEqual(self.lic_tit.articulo.cod_licencia, "T-14")
        self.assertTrue(LicenciaArticulo.objects.filter(cod_licencia="T-14").exists())

    def test_reemplaza_y_borra(self):
        salida = StringIO()
        call_command("cargar_nomenclador", "--reemplazar-inventados", "--confirmar", stdout=salida)
        self.lic_tit.refresh_from_db()
        self.lic_particulares.refresh_from_db()
        self.assertEqual(self.lic_tit.articulo.cod_licencia, "1-1-1")
        self.assertEqual(self.lic_particulares.articulo.cod_licencia, "2-4-1")
        self.assertFalse(LicenciaArticulo.objects.filter(cod_licencia__startswith="T-").exists())
        self.assertIn("T-14 → 1-1-1", salida.getvalue())

    def test_sin_el_motivo_para_su_situacion_pasa_a_inasistencias(self):
        # Una licencia de interino con T-20: fuerza mayor no existe para interinos.
        LicenciaOtorgada.objects.filter(pk=self.lic_particulares.pk).update(
            designacion=self.int_, sit_rev="Interino",
        )
        resultado = reemplazar_inventados()
        self.assertEqual(resultado.sin_equivalente, [])
        self.lic_particulares.refresh_from_db()
        self.assertEqual(self.lic_particulares.articulo.cod_licencia, "2-13-3")
        self.assertIn("T-20", resultado.borrados)

    def test_sin_ningun_destino_no_se_borra(self):
        from licencias import nomenclador

        LicenciaOtorgada.objects.filter(pk=self.lic_particulares.pk).update(
            designacion=self.int_, sit_rev="Interino",
        )
        original = nomenclador.REEMPLAZOS_INVENTADOS["T-20"]
        nomenclador.REEMPLAZOS_INVENTADOS["T-20"] = ("2-4-1",)
        try:
            resultado = reemplazar_inventados()
        finally:
            nomenclador.REEMPLAZOS_INVENTADOS["T-20"] = original
        self.assertEqual(len(resultado.sin_equivalente), 1)
        self.assertNotIn("T-20", resultado.borrados)
        self.assertTrue(LicenciaArticulo.objects.filter(cod_licencia="T-20").exists())
