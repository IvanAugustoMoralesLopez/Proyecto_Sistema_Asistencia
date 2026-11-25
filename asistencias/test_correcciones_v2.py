"""
Correcciones de asistencias según el análisis completo contra el Documento
de Requerimientos v2.0:

- RF-07: «Copiar lo del día anterior» llega al servidor como copiar.
- RF-09: el atajo de Pendientes pasa la I a LIC, LT o P, como Recepción.
- RF-11: un registro ya cargado se corrige aunque la designación se dé de baja.
- RF-12: aviso de las designaciones sin ningún horario cargado.
- RF-10 / RF-08: textos de pantalla que contradecían al sistema.
- RF-20: el calendario escolar queda en la bitácora.
- INC-01: las exportaciones CSV no dejan pasar fórmulas de Excel.
- Registrar / Editar asistencia: el combo muestra solo las licencias del
  docente elegido y elige la que cubre el día (marcas LIC y LT).
- Historial y Recepción: un filtro con error no muestra todo; nombre en
  cualquier orden, DNI con puntos, materias dadas de baja y textos.

RF-19 (tres operadoras) y RF-14 (licencia sin fecha de fin) se prueban en
tests.py, junto a las pruebas de concurrencia y de marcado de licencias.
"""

import csv
from datetime import date
from decimal import Decimal

from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.urls import reverse

from licencias.models import LicenciaOtorgada
from personal.models import Designacion, EspacioCurricular, Horario, Persona

from .forms import FiltroAsistenciaForm, FiltroRecepcionForm, RegistroAsistenciaForm
from .models import DiaNoLaborable, EventoAsistencia, MarcaAsistencia, RegistroAsistencia
from .services import (
    TIPO_LICENCIA,
    cargar_calendario_masivo,
    copiar_calendario,
    eliminar_dia_no_laborable,
    guardar_asistencia,
    guardar_dia_no_laborable,
    pendientes,
    resolver_pendiente,
)
from .test_pendientes import MIERCOLES, hoy_es
from .test_planilla_mes import PlanillaMesBase
from .tests import (
    LUNES,
    MARTES,
    PERMISOS_CALENDARIO,
    BaseAsistenciaTests,
    BasePlanillaTests,
    crear_usuario,
)
from .views._comun import celda_csv


# ───────────── RF-07: botón «Copiar lo del día anterior» ─────────────

class BotonCopiarTests(BasePlanillaTests):
    """
    El script de la pantalla desactivaba el botón antes del envío y el
    navegador no mandaba accion=copiar: la planilla se guardaba con «Asistió».
    El JavaScript no corre en estas pruebas; se comprueba que la pantalla trae
    el arreglo (el comportamiento real se verificó en un navegador).
    """

    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)
        self.respuesta = self.client.get(
            reverse("asistencia:planilla_rapida"),
            {"fecha": LUNES.isoformat(), "alcance": "todos"},
        )

    def test_la_planilla_tiene_el_boton_copiar(self):
        self.assertContains(self.respuesta, 'name="accion" value="copiar"')

    def test_el_script_manda_el_boton_apretado_aunque_lo_desactive(self):
        self.assertContains(self.respuesta, "evento.submitter")
        self.assertContains(self.respuesta, "data-copia-del-boton")

    def test_enter_en_la_planilla_guarda_y_no_copia(self):
        self.assertContains(self.respuesta, "planilla.requestSubmit(botonGuardar)")

    def test_copiar_no_guarda_nada(self):
        respuesta = self.client.post(
            reverse("asistencia:planilla_rapida"),
            {"fecha": LUNES.isoformat(), "alcance": "todos", "accion": "copiar"},
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(RegistroAsistencia.objects.filter(fecha=LUNES).exists())


# ───────────── RF-09: Pendientes pasa la I a la marca del formulario ─────────────

class PendientesConMarcaDelFormularioTests(BaseAsistenciaTests):
    def setUp(self):
        super().setUp()
        self.otra_materia = Designacion.objects.create(
            persona=self.persona, cargo=self.cargo, desde=date(2026, 3, 1)
        )
        self.faltas = [
            self.guardar(marca=self.marca_i, horas_inasistidas=Decimal("2")),
            self.guardar(
                designacion=self.otra_materia,
                marca=self.marca_i,
                horas_inasistidas=Decimal("3"),
            ),
        ]
        self.clave = pendientes(MIERCOLES)[0]["clave"]

    def resolver(self, **datos):
        with hoy_es(MIERCOLES):
            return resolver_pendiente(
                usuario=self.usuario, token=self.token, clave=self.clave, **datos
            )

    def recargar(self):
        for registro in self.faltas:
            registro.refresh_from_db()
        return self.faltas

    def test_llego_un_permiso_pasa_a_p_en_todas_las_materias(self):
        pendiente = self.resolver(
            respuesta="formulario", nueva_marca="P", nro_formulario="F-1"
        )

        self.assertEqual(pendiente["marca_nueva"].codigo, "P")
        for registro in self.recargar():
            self.assertEqual(registro.marca.codigo, "P")
            self.assertEqual(registro.estado_justificacion, "JUSTIFICADA")
            self.assertEqual(registro.nro_formulario, "F-1")
            self.assertIsNotNone(registro.resuelto_en)
            # P exige observaciones: se completan con el formulario.
            self.assertIn("formulario N° F-1", registro.observaciones)
        self.assertEqual(pendientes(MIERCOLES), [])

    def test_llego_una_licencia_pasa_a_lic_y_falta_cargarla(self):
        self.resolver(respuesta="formulario", nueva_marca="LIC")

        for registro in self.recargar():
            self.assertEqual(registro.marca.codigo, "LIC")
            self.assertIsNone(registro.resuelto_en)
        lista = pendientes(MIERCOLES)
        self.assertEqual(len(lista), 1)
        self.assertEqual(lista[0]["tipo"], TIPO_LICENCIA)

    def test_llego_un_largo_tratamiento_pasa_a_lt(self):
        self.resolver(respuesta="formulario", nueva_marca="lt")
        self.assertEqual({r.marca.codigo for r in self.recargar()}, {"LT"})

    def test_sin_elegir_marca_queda_como_inasistencia_justificada(self):
        pendiente = self.resolver(respuesta="formulario")

        self.assertIsNone(pendiente["marca_nueva"])
        for registro in self.recargar():
            self.assertEqual(registro.marca.codigo, "I")
            self.assertEqual(registro.estado_justificacion, "JUSTIFICADA")

    def test_elegir_marca_si_no_llego_el_formulario_se_rechaza(self):
        with self.assertRaises(ValidationError):
            self.resolver(respuesta="no_llego", nueva_marca="P")
        self.assertEqual({r.marca.codigo for r in self.recargar()}, {"I"})

    def test_una_marca_que_no_es_de_formulario_se_rechaza(self):
        with self.assertRaises(ValidationError):
            self.resolver(respuesta="formulario", nueva_marca="PR")
        self.assertEqual({r.marca.codigo for r in self.recargar()}, {"I"})

    def test_la_pantalla_ofrece_elegir_el_formulario(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.get(
            reverse("asistencia:planilla_rapida"), {"fecha": LUNES.isoformat()}
        )
        self.assertContains(respuesta, 'name="nueva_marca"')
        self.assertContains(respuesta, "Si llegó, ¿qué formulario es?")

    def test_la_vista_avisa_que_falta_cargar_la_licencia(self):
        self.client.force_login(self.usuario)
        with hoy_es(MIERCOLES):
            respuesta = self.client.post(
                reverse("asistencia:resolver_pendiente"),
                {
                    "clave": self.clave,
                    "accion": "resolver",
                    "respuesta": "formulario",
                    "nueva_marca": "LIC",
                },
            )
        mensajes = " ".join(str(m) for m in get_messages(respuesta.wsgi_request))
        self.assertIn("pasó a Licencia médica o especial (LIC)", mensajes)
        self.assertIn("Falta cargar la licencia", mensajes)


# ───────────── RF-11: corregir un registro de una designación dada de baja ─────────────

class CorreccionDeDesignacionDadaDeBajaTests(BaseAsistenciaTests):
    def setUp(self):
        super().setUp()
        self.registro = self.guardar()  # «Asistió» el lunes

    def dar_de_baja(self, **cambios):
        Designacion.objects.filter(pk=self.designacion.pk).update(activo=False, **cambios)
        self.designacion = Designacion.objects.select_related("persona").get(
            pk=self.designacion.pk
        )

    def corregir(self, designacion=None):
        return guardar_asistencia(
            usuario=self.usuario,
            token=self.token,
            datos={
                "designacion": designacion or self.designacion,
                "fecha": LUNES,
                "marca": self.marca_i,
                "horas_inasistidas": Decimal("2"),
                "licencia": None,
                "observaciones": "",
            },
            registro_id=self.registro.pk,
            motivo="Se cargó presente por error",
        )

    def test_se_corrige_aunque_la_designacion_se_haya_dado_de_baja(self):
        self.dar_de_baja()
        self.assertEqual(self.corregir().marca.codigo, "I")

    def test_se_corrige_aunque_el_legajo_se_haya_dado_de_baja(self):
        Persona.objects.filter(pk=self.persona.pk).update(activa=False)
        self.designacion = Designacion.objects.select_related("persona").get(
            pk=self.designacion.pk
        )
        self.assertEqual(self.corregir().marca.codigo, "I")

    def test_la_correccion_queda_en_la_bitacora_con_el_motivo(self):
        self.dar_de_baja()
        self.corregir()
        evento = EventoAsistencia.objects.filter(
            asistencia=self.registro, accion=EventoAsistencia.Accion.EDITAR
        ).get()
        self.assertEqual(evento.motivo, "Se cargó presente por error")

    def test_la_fecha_tiene_que_seguir_dentro_de_la_vigencia(self):
        self.dar_de_baja(hasta=date(2026, 9, 11))
        with self.assertRaisesMessage(ValidationError, "posterior al fin"):
            self.corregir()

    def test_no_se_carga_un_dia_nuevo_en_una_designacion_dada_de_baja(self):
        self.dar_de_baja()
        with self.assertRaisesMessage(ValidationError, "inactiva"):
            self.guardar(designacion=self.designacion, fecha=MARTES)

    def test_no_se_puede_pasar_el_registro_a_otra_designacion_dada_de_baja(self):
        otra = Designacion.objects.create(
            persona=self.persona, cargo=self.cargo, desde=date(2026, 3, 1), activo=False
        )
        with self.assertRaisesMessage(ValidationError, "inactiva"):
            self.corregir(designacion=otra)


# ───────────── RF-12: designaciones sin ningún horario cargado ─────────────

class AvisoSinHorarioTests(BasePlanillaTests):
    """
    PEREZ da clase el lunes en una designación y tiene otra sin ningún
    horario; GOMEZ no tiene ningún horario cargado.
    """

    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)
        Horario.objects.create(designacion=self.designacion, dia="LUN", horas_catedra=4)

    def ver(self, **extra):
        return self.client.get(
            reverse("asistencia:planilla_rapida"),
            {"fecha": LUNES.isoformat(), **extra},
        )

    def agente(self, respuesta, persona):
        return next(a for a in respuesta.context["agentes"] if a["persona"].pk == persona.pk)

    def test_avisa_la_designacion_del_docente_que_no_recibe_la_marca(self):
        respuesta = self.ver()
        self.assertEqual(self.agente(respuesta, self.persona)["sin_horario"], ["«Profesor»"])
        self.assertContains(respuesta, "horario cargado: no recibe la marca")

    def test_avisa_los_docentes_que_no_aparecen_en_la_lista(self):
        respuesta = self.ver()
        self.assertEqual(respuesta.context["fuera_sin_horario"], [self.persona_2])
        self.assertContains(respuesta, "sin ningún horario cargado no aparece en esta lista")
        self.assertContains(respuesta, "GOMEZ, ANA")

    def test_con_todos_los_docentes_no_hay_aviso(self):
        respuesta = self.ver(alcance="todos")
        self.assertEqual(respuesta.context["fuera_sin_horario"], [])
        self.assertEqual(self.agente(respuesta, self.persona)["sin_horario"], [])
        self.assertContains(respuesta, "· sin horario cargado")

    def test_un_horario_de_otro_dia_no_es_falta_de_horario(self):
        Horario.objects.create(designacion=self.perez_2, dia="MAR", horas_catedra=2)
        Horario.objects.create(designacion=self.gomez, dia="MAR", horas_catedra=2)
        respuesta = self.ver()
        self.assertEqual(self.agente(respuesta, self.persona)["sin_horario"], [])
        self.assertEqual(respuesta.context["fuera_sin_horario"], [])


# ───────────── RF-10 / RF-08: textos que contradecían al sistema ─────────────

class TextosCorregidosTests(BaseAsistenciaTests):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)

    def test_el_calendario_no_dice_que_bloquea_la_carga(self):
        self.client.force_login(crear_usuario("gestor", PERMISOS_CALENDARIO))
        respuesta = self.client.get(reverse("asistencia:crear_dia_no_laborable"))
        self.assertNotContains(respuesta, "no se podrá registrar")
        self.assertContains(respuesta, "se puede registrar asistencia igual")

    def test_la_asistencia_del_dia_no_habla_de_retirados(self):
        self.guardar(marca=self.marca_i, horas_inasistidas=Decimal("2"))
        respuesta = self.client.get(
            reverse("asistencia:registro_diario"), {"fecha": LUNES.isoformat()}
        )
        self.assertNotContains(respuesta, "se retir")
        self.assertContains(respuesta, "faltó")
        self.assertContains(respuesta, "Recepción de formularios")
        self.assertNotContains(respuesta, "Certificados y justificaciones")

    def test_la_recepcion_se_llama_como_en_el_menu(self):
        respuesta = self.client.get(reverse("asistencia:recepcion_formularios"))
        self.assertContains(respuesta, "<title>Recepción de formularios", html=False)


# ───────────── RF-20: el calendario escolar queda en la bitácora ─────────────

class CalendarioEnLaBitacoraTests(BaseAsistenciaTests):
    def setUp(self):
        super().setUp()
        self.gestor = crear_usuario("gestor", PERMISOS_CALENDARIO)

    def cargar(self, fecha=MARTES, dia_id=None, **datos):
        return guardar_dia_no_laborable(
            usuario=self.gestor,
            datos={
                "fecha": fecha,
                "tipo": DiaNoLaborable.Tipo.FERIADO,
                "descripcion": "Feriado de prueba",
                **datos,
            },
            dia_id=dia_id,
        )

    def eventos(self, accion):
        return EventoAsistencia.objects.filter(accion=accion).order_by("pk")

    def test_el_alta_queda_con_usuario_y_datos(self):
        self.cargar()
        evento = self.eventos(EventoAsistencia.Accion.CALENDARIO_ALTA).get()
        self.assertEqual(evento.usuario, self.gestor)
        self.assertIsNone(evento.antes)
        self.assertEqual(evento.despues["fecha"], "2026-09-15")
        self.assertIn("Feriado 15/09/2026 (Feriado de prueba)", evento.motivo)

    def test_la_modificacion_guarda_antes_y_despues(self):
        dia = self.cargar()
        self.cargar(dia_id=dia.pk, tipo=DiaNoLaborable.Tipo.ASUETO)
        evento = self.eventos(EventoAsistencia.Accion.CALENDARIO_EDITAR).get()
        self.assertEqual(evento.antes["tipo"], DiaNoLaborable.Tipo.FERIADO)
        self.assertEqual(evento.despues["tipo"], DiaNoLaborable.Tipo.ASUETO)

    def test_guardar_sin_cambios_no_deja_evento(self):
        dia = self.cargar()
        self.cargar(dia_id=dia.pk)
        self.assertFalse(self.eventos(EventoAsistencia.Accion.CALENDARIO_EDITAR).exists())

    def test_la_baja_guarda_lo_que_habia(self):
        dia = self.cargar()
        eliminar_dia_no_laborable(usuario=self.gestor, dia_id=dia.pk)
        evento = self.eventos(EventoAsistencia.Accion.CALENDARIO_BAJA).get()
        self.assertEqual(evento.antes["fecha"], "2026-09-15")
        self.assertIsNone(evento.despues)

    def test_copiar_el_anio_y_la_carga_masiva_quedan_registradas(self):
        self.cargar()
        copiar_calendario(usuario=self.gestor, anio_origen=2026, anio_destino=2027)
        cargar_calendario_masivo(
            usuario=self.gestor,
            texto="2026-10-12 Diversidad cultural",
            tipo=DiaNoLaborable.Tipo.FERIADO,
        )
        motivos = list(
            self.eventos(EventoAsistencia.Accion.CALENDARIO_ALTA).values_list("motivo", flat=True)
        )
        self.assertEqual(len(motivos), 3)
        self.assertTrue(motivos[1].startswith("Copia del calendario 2026: "))
        self.assertTrue(motivos[2].startswith("Carga masiva: "))

    def test_las_acciones_tienen_nombre_para_la_bitacora(self):
        self.assertEqual(
            EventoAsistencia.Accion("CALENDARIO_ALTA").label, "Alta en el calendario"
        )


# ───────────── INC-01: CSV sin fórmulas de Excel ─────────────

class CeldaCsvTests(BaseAsistenciaTests):
    def test_antepone_apostrofo_a_lo_que_excel_toma_como_formula(self):
        for valor in ("=1+1", "+54", "-2", "@SUMA(A1)", "\t=1", "\r=1"):
            self.assertEqual(celda_csv(valor), "'" + valor)

    def test_deja_igual_el_texto_comun(self):
        self.assertEqual(celda_csv("PEREZ, JUAN"), "PEREZ, JUAN")
        self.assertEqual(celda_csv(None), "")
        self.assertEqual(celda_csv(30123456), "30123456")


class ExportacionHistorialSinFormulasTests(BaseAsistenciaTests):
    def test_nombre_y_formulario_no_se_ejecutan_en_excel(self):
        Persona.objects.filter(pk=self.persona.pk).update(apellido_nombre="=1+1, MALICIOSO")
        self.guardar(
            marca=self.marca_i,
            horas_inasistidas=Decimal("2"),
            formulario_recibido=True,
            nro_formulario="@SUMA(A1)",
        )
        self.client.force_login(self.usuario)

        respuesta = self.client.get(reverse("asistencia:exportar_csv"))

        filas = list(csv.reader(respuesta.content.decode("utf-8-sig").splitlines(), delimiter=";"))
        self.assertEqual(filas[1][2], "'=1+1, MALICIOSO")
        self.assertEqual(filas[1][9], "'@SUMA(A1)")


class ExportacionMesSinFormulasTests(PlanillaMesBase):
    def test_el_nombre_no_se_ejecuta_en_excel(self):
        Persona.objects.filter(pk=self.docente.pk).update(apellido_nombre="-CMD, ALGUIEN")
        RegistroAsistencia.objects.create(
            designacion=self.en_software,
            fecha=LUNES,
            marca=MarcaAsistencia.objects.get(codigo="I"),
        )
        self.client.force_login(self.usuario)

        respuesta = self.client.get(
            reverse("asistencia:planilla_mes_csv"), {"mes": "2026-09"}
        )

        filas = list(csv.reader(respuesta.content.decode("utf-8-sig").splitlines(), delimiter=";"))
        nombres = [fila[1] for fila in filas[2:]]
        self.assertIn("'-CMD, ALGUIEN", nombres)


# ───────────── Registrar / Editar asistencia: licencias del docente elegido ─────────────

class LicenciasDelDocenteTests(BaseAsistenciaTests):
    """
    El combo de licencias mostraba las de todos los docentes y no elegía
    ninguna sola: el script esperaba una marca que «exige licencia» y en v2
    ninguna la exige. Ahora cada opción publica su designación y su período,
    y cada marca si es de licencia (LIC, LT); la pantalla filtra y elige.
    El JavaScript no corre en estas pruebas (se verificó en un navegador).
    """

    def setUp(self):
        super().setUp()
        self.licencia = self.crear_licencia(desde=LUNES, hasta=MARTES)
        otra_persona = Persona.objects.create(
            dni="30999888", apellido_nombre="GOMEZ, ANA", sexo="F"
        )
        self.otra_designacion = Designacion.objects.create(
            persona=otra_persona, cargo=self.cargo, desde=date(2026, 3, 1)
        )
        self.licencia_ajena = LicenciaOtorgada.objects.create(
            designacion=self.otra_designacion,
            articulo=self.licencia.articulo,
            sit_rev="Titular",
            desde=LUNES,
            hasta=None,
        )

    def atributos(self, form, campo):
        """{valor de la opción: atributos} de un combo del formulario."""
        return {
            str(opcion.data["value"]): opcion.data["attrs"]
            for opcion in form[campo].subwidgets
            if str(opcion.data["value"])
        }

    def test_cada_licencia_dice_de_que_docente_es_y_que_dias_cubre(self):
        opciones = self.atributos(RegistroAsistenciaForm(), "licencia")

        propia = opciones[str(self.licencia.pk)]
        self.assertEqual(propia["data-designacion"], str(self.designacion.pk))
        self.assertEqual(propia["data-desde"], "2026-09-14")
        self.assertEqual(propia["data-hasta"], "2026-09-15")

        ajena = opciones[str(self.licencia_ajena.pk)]
        self.assertEqual(ajena["data-designacion"], str(self.otra_designacion.pk))
        self.assertEqual(ajena["data-hasta"], "")  # abierta, sin fecha de fin

    def test_las_marcas_de_licencia_se_distinguen(self):
        opciones = self.atributos(RegistroAsistenciaForm(), "marca")
        de_licencia = {
            marca.codigo: opciones[str(marca.pk)]["data-de-licencia"]
            for marca in MarcaAsistencia.vigentes()
        }
        self.assertEqual(
            de_licencia,
            {"LIC": "1", "LT": "1", "PR": "0", "I": "0", "P": "0"},
        )

    def test_al_editar_se_ofrecen_las_licencias_aunque_la_designacion_este_de_baja(self):
        registro = self.guardar(marca=self.marca_lic, horas_inasistidas=Decimal("2"))
        Designacion.objects.filter(pk=self.designacion.pk).update(activo=False)

        opciones = self.atributos(RegistroAsistenciaForm(instance=registro), "licencia")

        self.assertIn(str(self.licencia.pk), opciones)

    def test_la_pantalla_filtra_por_docente_y_elige_la_que_cubre_el_dia(self):
        registro = self.guardar(marca=self.marca_lic, horas_inasistidas=Decimal("2"))
        self.client.force_login(self.usuario)

        respuesta = self.client.get(
            reverse("asistencia:editar_asistencia", args=[registro.pk])
        )

        self.assertContains(respuesta, f'data-designacion="{self.designacion.pk}"')
        self.assertContains(respuesta, 'data-de-licencia="1"')
        self.assertContains(respuesta, "function filtrarLicencias()")
        self.assertContains(respuesta, "Se eligió la licencia que cubre el ")


class FechasQueElNavegadorMuestraTests(BaseAsistenciaTests):
    """
    Un <input type="date"> solo muestra valores en formato ISO. Con es-ar
    Django escribía «14/09/2026»: el Día aparecía vacío al editar (y sin día
    tampoco se elegía la licencia) y la recepción no traía la fecha de hoy.
    """

    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)

    def test_editar_muestra_el_dia_del_registro(self):
        registro = self.guardar()
        respuesta = self.client.get(
            reverse("asistencia:editar_asistencia", args=[registro.pk])
        )
        self.assertContains(respuesta, 'name="fecha" value="2026-09-14"')
        self.assertNotContains(respuesta, 'value="14/09/2026"')

    def test_registrar_muestra_el_dia_pedido(self):
        respuesta = self.client.get(
            reverse("asistencia:crear_asistencia"), {"fecha": LUNES.isoformat()}
        )
        self.assertContains(respuesta, 'name="fecha" value="2026-09-14"')

    def test_recepcion_trae_la_fecha_de_hoy(self):
        registro = self.guardar(marca=self.marca_i, horas_inasistidas=Decimal("2"))
        with hoy_es(MIERCOLES):
            respuesta = self.client.get(
                reverse("asistencia:recepcionar_formulario", args=[registro.pk])
            )
        self.assertContains(
            respuesta, f'name="fecha_recepcion" value="{MIERCOLES.isoformat()}"'
        )


# ───────────── Historial y Recepción de formularios: filtros ─────────────

class FiltrosDelHistorialTests(BaseAsistenciaTests):
    """
    Comprobado en una base temporal antes del arreglo: con un filtro con
    error se ignoraban todos y se veía (y exportaba) todo; el nombre solo se
    encontraba escrito como en el legajo; el DNI con puntos no se encontraba
    y las materias dadas de baja no se podían elegir.
    """

    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)
        self.historia = EspacioCurricular.objects.create(nombre="Historia")
        gomez = Persona.objects.create(
            dni="27000111", apellido_nombre="GÓMEZ, Ana María", sexo="F"
        )
        self.de_gomez = Designacion.objects.create(
            persona=gomez,
            cargo=self.cargo,
            espacio_curricular=self.historia,
            desde=date(2026, 3, 1),
        )
        self.guardar()  # PEREZ, JUAN · lunes · Asistió
        self.guardar(fecha=MARTES, marca=self.marca_i, horas_inasistidas=Decimal("2"))
        self.gomez = {
            self.guardar(designacion=self.de_gomez),
            self.guardar(
                designacion=self.de_gomez,
                fecha=MARTES,
                marca=self.marca_i,
                horas_inasistidas=Decimal("2"),
            ),
        }

    def historial(self, **filtros):
        return self.client.get(reverse("asistencia:historial"), filtros)

    def encontrados(self, respuesta):
        return set(respuesta.context["pagina"].object_list)

    def fechas_invertidas(self, **otros):
        return {"desde": MARTES.isoformat(), "hasta": LUNES.isoformat(), **otros}

    # ── Un filtro con error ──
    def test_un_filtro_con_error_no_muestra_nada(self):
        respuesta = self.historial(**self.fechas_invertidas(dni="30123456"))

        self.assertEqual(respuesta.context["pagina"].paginator.count, 0)
        self.assertTrue(respuesta.context["filtro_con_error"])
        self.assertContains(respuesta, "La fecha final debe ser igual o posterior a la inicial.")
        self.assertContains(respuesta, "Hay un filtro con un error")
        self.assertNotContains(respuesta, "con los filtros elegidos")

    def test_una_opcion_que_no_existe_tampoco_muestra_todo(self):
        respuesta = self.historial(marca="9999")
        self.assertEqual(respuesta.context["pagina"].paginator.count, 0)

    def test_el_excel_con_un_filtro_con_error_no_exporta_nada(self):
        respuesta = self.client.get(
            reverse("asistencia:exportar_csv"), self.fechas_invertidas()
        )
        filas = list(csv.reader(respuesta.content.decode("utf-8-sig").splitlines(), delimiter=";"))

        self.assertEqual(filas[0][0], "Fecha")
        self.assertEqual(len(filas), 2)
        self.assertIn("Un filtro tiene un error", filas[1][0])

    def test_recepcion_con_un_filtro_con_error_no_muestra_nada(self):
        respuesta = self.client.get(
            reverse("asistencia:recepcion_formularios"),
            self.fechas_invertidas(dni="27000111"),
        )
        self.assertEqual(respuesta.context["pagina"].paginator.count, 0)
        self.assertContains(respuesta, "Hay un filtro con un error")

    def test_sin_errores_los_filtros_siguen_funcionando(self):
        self.assertEqual(self.encontrados(self.historial(dni="27000111")), self.gomez)
        martes = self.historial(desde=MARTES.isoformat(), hasta=MARTES.isoformat())
        self.assertEqual(
            {r.marca.codigo for r in self.encontrados(martes)}, {"I"}
        )
        self.assertEqual(martes.context["pagina"].paginator.count, 2)

    # ── Nombre y DNI ──
    def test_el_nombre_se_busca_por_palabras_en_cualquier_orden(self):
        for texto in ("gomez ana", "Ana Gómez", "GÓMEZ, Ana", "maria gomez", "  ana   gomez "):
            self.assertEqual(
                self.encontrados(self.historial(apellido_nombre=texto)), self.gomez, texto
            )
        self.assertEqual(self.encontrados(self.historial(apellido_nombre="ana perez")), set())

    def test_el_dni_admite_puntos_y_espacios(self):
        for texto in ("27.000.111", "27 000 111", " 27000111 "):
            self.assertEqual(
                self.encontrados(self.historial(dni=texto)), self.gomez, texto
            )

    # ── Materias dadas de baja ──
    def test_se_puede_buscar_una_materia_dada_de_baja(self):
        EspacioCurricular.objects.filter(pk=self.historia.pk).update(activo=False)

        self.assertContains(self.historial(), "Historia (dada de baja)")
        respuesta = self.historial(espacio_curricular=str(self.historia.pk))
        self.assertFalse(respuesta.context["filtro_con_error"])
        self.assertEqual(self.encontrados(respuesta), self.gomez)

    # ── Textos y «(activos)» ──
    def test_los_filtros_hablan_de_formulario(self):
        self.assertEqual(
            FiltroAsistenciaForm().fields["estado_justificacion"].label, "Formulario"
        )
        recepcion = FiltroRecepcionForm().fields["estado_justificacion"]
        self.assertEqual(recepcion.label, "Formulario")
        self.assertIn(
            "Pendientes (sin formulario o en trámite)", dict(recepcion.choices).values()
        )

    def test_recepcion_buscar_con_todo_vacio_no_marca_filtros_activos(self):
        url = reverse("asistencia:recepcion_formularios")
        vacio = {"dni": "", "apellido_nombre": "", "estado_justificacion": "PENDIENTES"}

        self.assertNotContains(self.client.get(url, vacio), "(activos)")
        self.assertContains(self.client.get(url, {**vacio, "dni": "27000111"}), "(activos)")

    def test_una_sola_fecha_completa_la_otra(self):
        for url in ("asistencia:historial", "asistencia:recepcion_formularios"):
            self.assertContains(
                self.client.get(reverse(url)), "otra.dataset.completada", msg_prefix=url
            )
