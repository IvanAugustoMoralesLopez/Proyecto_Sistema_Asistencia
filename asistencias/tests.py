import importlib
import os
import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.messages import get_messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from licencias.models import LicenciaArticulo, LicenciaOtorgada
from personal.models import Cargo, Carrera, Designacion, EspacioCurricular, Persona

from .forms import RegistroAsistenciaForm
from .models import (
    CODIGOS_MARCA,
    CierreDiario,
    CierreMensual,
    ControlConcurrencia,
    DiaNoLaborable,
    EventoAsistencia,
    MarcaAsistencia,
    RegistroAsistencia,
    SesionEdicion,
    licencia_cubre_fecha,
)
from .services import (
    MAX_OPERADORES,
    adquirir_sesion_edicion,
    PlanillaConErrores,
    cerrar_dia,
    cerrar_mes,
    eliminar_dia_no_laborable,
    guardar_asistencia,
    guardar_dia_no_laborable,
    guardar_planilla,
    liberar_sesion_edicion,
    motivo_dia_no_laborable,
    reabrir_mes,
    recepcionar_formulario,
    registros_cargados,
    renovar_sesion_edicion,
    validar_asistencia,
)

User = get_user_model()


# Permisos de esta app que se asignan a los usuarios de prueba de a uno:
# los tests no dependen de qué perfiles los otorguen en producción.
PERMISOS_LECTURA = ("view_registroasistencia",)
PERMISOS_CALENDARIO = (
    "add_dianolaborable",
    "change_dianolaborable",
    "delete_dianolaborable",
)
PERMISOS_CARGA = PERMISOS_LECTURA + (
    "add_registroasistencia",
    "change_registroasistencia",
    "recepcionar_formulario",
    "cerrar_jornada",
)
PERMISOS_SUPERVISION = PERMISOS_CARGA + (
    "validar_registro",
    "modificar_jornada_cerrada",
    "cerrar_periodo",
)


def crear_usuario(username, permisos=()):
    # Sin contraseña: los tests entran con force_login, y hashear una
    # (PBKDF2) cuesta ~0,35 s por usuario, casi todo el tiempo de la suite.
    usuario = User.objects.create_user(username)
    encontrados = Permission.objects.filter(
        content_type__app_label="asistencias",
        codename__in=permisos,
    )
    assert encontrados.count() == len(set(permisos)), "permiso inexistente"
    usuario.user_permissions.add(*encontrados)
    return usuario

# Fechas fijas del pasado para no depender de la fecha de ejecución.
LUNES = date(2026, 9, 14)
MARTES = date(2026, 9, 15)
SABADO = date(2026, 9, 12)
DOMINGO = date(2026, 9, 13)


class BaseAsistenciaTests(TestCase):
    """Datos comunes: un docente con una designación vigente y un operador."""

    def setUp(self):
        self.persona = Persona.objects.create(
            dni="30123456",
            apellido_nombre="PEREZ, JUAN",
            sexo="M",
        )
        self.cargo = Cargo.objects.create(
            codigo="PROF",
            descripcion="Profesor",
        )
        self.designacion = Designacion.objects.create(
            persona=self.persona,
            cargo=self.cargo,
            desde=date(2026, 3, 1),
        )
        self.usuario = crear_usuario("operador", PERMISOS_SUPERVISION)
        self.token = str(uuid.uuid4())
        adquirir_sesion_edicion(self.usuario, self.token)

        self.marca_p = MarcaAsistencia.objects.get(codigo="P")
        self.marca_i = MarcaAsistencia.objects.get(codigo="I")
        self.marca_lic = MarcaAsistencia.objects.get(codigo="LIC")
        self.marca_pr = MarcaAsistencia.objects.get(codigo="PR")

    def abrir_sesion(self, usuario):
        """Sesión de edición para otro usuario, respetando el límite de operadores."""
        SesionEdicion.objects.update(activa=False)
        token = str(uuid.uuid4())
        adquirir_sesion_edicion(usuario, token)
        return token

    def guardar(self, **cambios):
        datos = {
            "designacion": self.designacion,
            "fecha": LUNES,
            "marca": self.marca_p,
            "horas_inasistidas": Decimal("0"),
            "licencia": None,
            "observaciones": "",
        }
        datos.update(cambios)
        return guardar_asistencia(
            usuario=self.usuario,
            token=self.token,
            datos=datos,
        )

    def crear_licencia(self, desde=LUNES, hasta=None, designacion=None):
        articulo = LicenciaArticulo.objects.create(
            cod_licencia="01.01.04",
            articulo="149-A",
            tipo_licencia="Enfermedad común",
            categoria_informe="Enfermedad común",
            sit_rev="Titular",
            goce_haberes="Con goce de haberes",
            autoridad="Director",
            plazo="15 días",
        )
        return LicenciaOtorgada.objects.create(
            designacion=designacion or self.designacion,
            articulo=articulo,
            sit_rev="Titular",
            desde=desde,
            hasta=hasta,
        )


class CatalogoMarcasTests(BaseAsistenciaTests):
    """RF-08: catálogo cerrado de marcas diarias."""

    def test_el_catalogo_contiene_exactamente_las_cinco_marcas(self):
        self.assertEqual(
            set(MarcaAsistencia.vigentes().values_list("codigo", flat=True)),
            set(CODIGOS_MARCA),
        )

    def test_p_es_presente_y_pr_es_presente_retirado(self):
        self.assertEqual(self.marca_p.descripcion, "Presente")
        self.assertFalse(self.marca_p.computa_inasistencia)
        self.assertEqual(self.marca_pr.descripcion, "Presente retirado")
        self.assertTrue(self.marca_pr.computa_inasistencia)

    def test_una_marca_fuera_del_catalogo_no_esta_vigente(self):
        MarcaAsistencia.objects.create(codigo="XX", descripcion="Otra")
        self.assertFalse(MarcaAsistencia.vigentes().filter(codigo="XX").exists())

    def test_el_formulario_solo_ofrece_marcas_del_catalogo(self):
        MarcaAsistencia.objects.create(codigo="XX", descripcion="Otra")
        form = RegistroAsistenciaForm()
        codigos = set(form.fields["marca"].queryset.values_list("codigo", flat=True))
        self.assertEqual(codigos, set(CODIGOS_MARCA))

    def test_inasistencia_exige_horas(self):
        with self.assertRaises(ValidationError):
            self.guardar(marca=self.marca_i, horas_inasistidas=Decimal("0"))

    def test_inasistencia_con_horas_se_guarda(self):
        registro = self.guardar(marca=self.marca_i, horas_inasistidas=Decimal("4"))
        self.assertEqual(registro.horas_inasistidas, Decimal("4"))

    def test_presente_descarta_las_horas(self):
        registro = self.guardar(marca=self.marca_p, horas_inasistidas=Decimal("3"))
        self.assertEqual(registro.horas_inasistidas, Decimal("0"))

    def test_presente_retirado_exige_observacion(self):
        with self.assertRaises(ValidationError):
            self.guardar(marca=self.marca_pr, horas_inasistidas=Decimal("2"))

        registro = self.guardar(
            marca=self.marca_pr,
            horas_inasistidas=Decimal("2"),
            observaciones="Se retiró por una urgencia familiar.",
        )
        self.assertEqual(registro.marca.codigo, "PR")

    def test_licencia_exige_licencia_vinculada(self):
        with self.assertRaises(ValidationError):
            self.guardar(marca=self.marca_lic, horas_inasistidas=Decimal("4"))


class LicenciaVinculadaTests(BaseAsistenciaTests):
    """La licencia ya no tiene estado y puede tener `hasta` nulo."""

    def test_el_formulario_se_instancia_sin_errores(self):
        RegistroAsistenciaForm()

    def test_licencia_cubre_fecha_con_hasta_nulo(self):
        licencia = self.crear_licencia(desde=LUNES, hasta=None)
        self.assertTrue(licencia_cubre_fecha(licencia, LUNES))
        self.assertTrue(licencia_cubre_fecha(licencia, LUNES + timedelta(days=90)))
        self.assertFalse(licencia_cubre_fecha(licencia, LUNES - timedelta(days=1)))

    def test_licencia_cubre_fecha_con_rango_cerrado(self):
        licencia = self.crear_licencia(desde=LUNES, hasta=MARTES)
        self.assertTrue(licencia_cubre_fecha(licencia, MARTES))
        self.assertFalse(licencia_cubre_fecha(licencia, MARTES + timedelta(days=1)))

    def test_guardar_con_licencia_abierta(self):
        licencia = self.crear_licencia(desde=LUNES, hasta=None)
        registro = self.guardar(
            marca=self.marca_lic,
            horas_inasistidas=Decimal("4"),
            licencia=licencia,
        )
        self.assertEqual(registro.licencia, licencia)

    def test_fecha_fuera_del_periodo_de_la_licencia(self):
        licencia = self.crear_licencia(desde=LUNES, hasta=LUNES)
        with self.assertRaises(ValidationError):
            self.guardar(
                fecha=MARTES,
                marca=self.marca_lic,
                horas_inasistidas=Decimal("4"),
                licencia=licencia,
            )

    def test_licencia_de_otra_designacion(self):
        otra = Designacion.objects.create(
            persona=self.persona,
            cargo=self.cargo,
            desde=date(2026, 3, 1),
        )
        licencia = self.crear_licencia(designacion=otra)
        with self.assertRaises(ValidationError):
            self.guardar(
                marca=self.marca_lic,
                horas_inasistidas=Decimal("4"),
                licencia=licencia,
            )


class GuardarAsistenciaTests(BaseAsistenciaTests):
    def test_crear_registra_el_evento_de_auditoria(self):
        registro = self.guardar()
        evento = EventoAsistencia.objects.get(asistencia=registro)
        self.assertEqual(evento.accion, EventoAsistencia.Accion.CREAR)
        self.assertEqual(evento.usuario, self.usuario)
        self.assertIsNone(evento.antes)
        self.assertEqual(evento.despues["marca"], "P")

    def test_editar_guarda_antes_despues_y_motivo(self):
        registro = self.guardar()
        guardar_asistencia(
            usuario=self.usuario,
            token=self.token,
            datos={
                "designacion": self.designacion,
                "fecha": LUNES,
                "marca": self.marca_i,
                "horas_inasistidas": Decimal("2"),
                "licencia": None,
                "observaciones": "",
            },
            registro_id=registro.pk,
            motivo="Error de carga",
        )
        evento = EventoAsistencia.objects.filter(
            asistencia=registro,
            accion=EventoAsistencia.Accion.EDITAR,
        ).get()
        self.assertEqual(evento.antes["marca"], "P")
        self.assertEqual(evento.despues["marca"], "I")
        self.assertEqual(evento.motivo, "Error de carga")

    def test_no_permite_dos_registros_para_la_misma_designacion_y_fecha(self):
        self.guardar()
        with self.assertRaises(ValidationError):
            self.guardar()

    def test_sin_sesion_de_edicion_se_deniega(self):
        with self.assertRaises(PermissionDenied):
            guardar_asistencia(
                usuario=self.usuario,
                token=str(uuid.uuid4()),
                datos={
                    "designacion": self.designacion,
                    "fecha": LUNES,
                    "marca": self.marca_p,
                },
            )

    def test_designacion_inactiva(self):
        self.designacion.activo = False
        self.designacion.save()
        with self.assertRaises(ValidationError):
            self.guardar()

    def test_persona_inactiva(self):
        self.persona.activa = False
        self.persona.save()
        with self.assertRaises(ValidationError):
            self.guardar()

    def test_fecha_anterior_al_inicio_de_la_designacion(self):
        with self.assertRaises(ValidationError):
            self.guardar(fecha=date(2026, 2, 27))

    def test_fecha_posterior_al_fin_de_la_designacion(self):
        self.designacion.hasta = date(2026, 9, 11)
        self.designacion.save()
        with self.assertRaises(ValidationError):
            self.guardar()


class DiasNoLaborablesTests(BaseAsistenciaTests):
    """RF-10: no hay obligación de marcado en feriados, asuetos ni fines de semana."""

    def test_un_dia_habil_no_tiene_motivo(self):
        self.assertIsNone(motivo_dia_no_laborable(LUNES))

    def test_los_fines_de_semana_no_son_laborables(self):
        self.assertIn("fin de semana", motivo_dia_no_laborable(SABADO))
        self.assertIn("fin de semana", motivo_dia_no_laborable(DOMINGO))

    def test_no_se_registra_asistencia_en_fin_de_semana(self):
        with self.assertRaises(ValidationError):
            self.guardar(fecha=SABADO)
        self.assertFalse(RegistroAsistencia.objects.exists())

    def test_no_se_registra_asistencia_en_feriado(self):
        DiaNoLaborable.objects.create(
            fecha=MARTES,
            tipo=DiaNoLaborable.Tipo.FERIADO,
            descripcion="Feriado de prueba",
        )
        self.assertIn("feriado", motivo_dia_no_laborable(MARTES))
        with self.assertRaises(ValidationError):
            self.guardar(fecha=MARTES)

    def test_tampoco_en_asuetos_ni_dias_inhabiles(self):
        for fecha, tipo in (
            (MARTES, DiaNoLaborable.Tipo.ASUETO),
            (MARTES + timedelta(days=1), DiaNoLaborable.Tipo.INHABIL),
        ):
            DiaNoLaborable.objects.create(fecha=fecha, tipo=tipo)
            with self.assertRaises(ValidationError):
                self.guardar(fecha=fecha)

    def test_el_formulario_marca_el_error_en_la_fecha(self):
        DiaNoLaborable.objects.create(fecha=MARTES)
        form = RegistroAsistenciaForm(
            {
                "designacion": self.designacion.pk,
                "fecha": MARTES.isoformat(),
                "marca": self.marca_p.pk,
                "horas_inasistidas": "0",
                "observaciones": "",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("fecha", form.errors)

    def test_la_pantalla_diaria_informa_el_motivo(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.get(
            reverse("asistencia:registro_diario"),
            {"fecha": SABADO.isoformat()},
        )
        self.assertContains(respuesta, "es fin de semana")
        self.assertContains(respuesta, "No hay obligación de marcado")


class FinDeSemanaDePruebaTests(BaseAsistenciaTests):
    """El interruptor de pruebas manuales solo actúa con la variable y DEBUG."""

    VARIABLE = {"ASISTENCIA_PERMITIR_FIN_DE_SEMANA": "1"}

    @override_settings(DEBUG=True)
    @mock.patch.dict(os.environ, VARIABLE)
    def test_con_la_variable_y_debug_el_fin_de_semana_es_habil(self):
        self.assertIsNone(motivo_dia_no_laborable(SABADO))
        self.assertIsNone(motivo_dia_no_laborable(DOMINGO))
        self.guardar(fecha=DOMINGO)

    @override_settings(DEBUG=True)
    @mock.patch.dict(os.environ, VARIABLE)
    def test_los_feriados_siguen_bloqueando(self):
        DiaNoLaborable.objects.create(fecha=SABADO, descripcion="Feriado")
        self.assertIn("feriado", motivo_dia_no_laborable(SABADO))

    @override_settings(DEBUG=False)
    @mock.patch.dict(os.environ, VARIABLE)
    def test_sin_debug_la_variable_no_habilita_el_fin_de_semana(self):
        self.assertIn("fin de semana", motivo_dia_no_laborable(SABADO))

    @override_settings(DEBUG=True)
    @mock.patch.dict(os.environ, {"ASISTENCIA_PERMITIR_FIN_DE_SEMANA": "0"})
    def test_sin_la_variable_activa_el_fin_de_semana_sigue_bloqueado(self):
        self.assertIn("fin de semana", motivo_dia_no_laborable(DOMINGO))


class EdicionDeRegistroValidadoTests(BaseAsistenciaTests):
    """RF-11: corregir un registro validado exige motivo y lo devuelve a borrador."""

    def editar(self, registro, motivo="", **cambios):
        datos = {
            "designacion": self.designacion,
            "fecha": LUNES,
            "marca": self.marca_i,
            "horas_inasistidas": Decimal("2"),
            "licencia": None,
            "observaciones": "",
        }
        datos.update(cambios)
        return guardar_asistencia(
            usuario=self.usuario,
            token=self.token,
            datos=datos,
            registro_id=registro.pk,
            motivo=motivo,
        )

    def test_editar_un_borrador_no_exige_motivo(self):
        registro = self.guardar()
        actualizado = self.editar(registro)
        self.assertEqual(actualizado.marca.codigo, "I")
        self.assertEqual(
            actualizado.estado_registro, RegistroAsistencia.Estado.BORRADOR
        )

    def test_editar_un_validado_sin_motivo_se_rechaza(self):
        registro = self.guardar()
        validar_asistencia(
            usuario=self.usuario, token=self.token, registro_id=registro.pk
        )
        for motivo in ("", "   ", "corto"):
            with self.assertRaises(ValidationError):
                self.editar(registro, motivo=motivo)

        registro.refresh_from_db()
        self.assertEqual(registro.marca.codigo, "P")
        self.assertEqual(
            registro.estado_registro, RegistroAsistencia.Estado.VALIDADO
        )

    def test_editar_un_validado_con_motivo_vuelve_a_borrador(self):
        registro = self.guardar()
        validar_asistencia(
            usuario=self.usuario, token=self.token, registro_id=registro.pk
        )
        actualizado = self.editar(
            registro, motivo="Se cargó presente por error tipográfico"
        )
        self.assertEqual(actualizado.marca.codigo, "I")
        self.assertEqual(
            actualizado.estado_registro, RegistroAsistencia.Estado.BORRADOR
        )

        evento = EventoAsistencia.objects.filter(
            asistencia=registro, accion=EventoAsistencia.Accion.EDITAR
        ).get()
        self.assertEqual(evento.antes["estado_registro"], "VALIDADO")
        self.assertEqual(evento.despues["estado_registro"], "BORRADOR")

    def test_un_registro_corregido_debe_validarse_antes_de_cerrar_el_mes(self):
        registro = self.guardar()
        validar_asistencia(
            usuario=self.usuario, token=self.token, registro_id=registro.pk
        )
        self.editar(registro, motivo="Se cargó presente por error tipográfico")
        with self.assertRaises(ValidationError):
            cerrar_mes(
                usuario=self.usuario, token=self.token, anio=2026, mes=9
            )

    def test_la_pantalla_de_edicion_avisa_que_vuelve_a_borrador(self):
        registro = self.guardar()
        validar_asistencia(
            usuario=self.usuario, token=self.token, registro_id=registro.pk
        )
        self.client.force_login(self.usuario)
        respuesta = self.client.get(
            reverse("asistencia:editar_asistencia", args=[registro.pk])
        )
        self.assertContains(respuesta, "volverá a borrador")


class RecepcionFormulariosTests(BaseAsistenciaTests):
    """RF-09: Injustificada -> En trámite / Justificada al recibir el papel."""

    Justificacion = RegistroAsistencia.EstadoJustificacion

    def inasistencia(self, **cambios):
        datos = {"marca": self.marca_i, "horas_inasistidas": Decimal("4")}
        datos.update(cambios)
        return self.guardar(**datos)

    def recepcionar(self, registro, estado, **datos):
        return recepcionar_formulario(
            usuario=self.usuario,
            token=self.token,
            registro_id=registro.pk,
            nuevo_estado=estado,
            **datos,
        )

    def test_una_inasistencia_nace_injustificada(self):
        self.assertEqual(
            self.inasistencia().estado_justificacion,
            self.Justificacion.INJUSTIFICADA,
        )

    def test_un_presente_no_lleva_justificacion(self):
        self.assertEqual(
            self.guardar().estado_justificacion, self.Justificacion.NO_APLICA
        )

    def test_pasa_a_en_tramite_con_numero_de_formulario(self):
        registro = self.inasistencia()
        actualizado = self.recepcionar(
            registro,
            self.Justificacion.EN_TRAMITE,
            nro_formulario=" F-123 ",
            fecha_recepcion=LUNES,
        )
        self.assertEqual(
            actualizado.estado_justificacion, self.Justificacion.EN_TRAMITE
        )
        self.assertEqual(actualizado.nro_formulario, "F-123")
        self.assertEqual(actualizado.fecha_recepcion, LUNES)
        self.assertEqual(actualizado.recepcionado_por, self.usuario)

    def test_la_fecha_de_recepcion_por_defecto_es_hoy(self):
        registro = self.inasistencia()
        actualizado = self.recepcionar(
            registro, self.Justificacion.JUSTIFICADA, nro_formulario="F-1"
        )
        self.assertEqual(actualizado.fecha_recepcion, timezone.localdate())

    def test_sin_numero_de_formulario_se_rechaza(self):
        registro = self.inasistencia()
        for estado in (
            self.Justificacion.EN_TRAMITE,
            self.Justificacion.JUSTIFICADA,
        ):
            with self.assertRaises(ValidationError):
                self.recepcionar(registro, estado, nro_formulario="  ")

    def test_la_fecha_de_recepcion_no_puede_ser_futura(self):
        registro = self.inasistencia()
        with self.assertRaises(ValidationError):
            self.recepcionar(
                registro,
                self.Justificacion.EN_TRAMITE,
                nro_formulario="F-1",
                fecha_recepcion=timezone.localdate() + timedelta(days=1),
            )

    def test_en_tramite_pasa_a_justificada(self):
        registro = self.inasistencia()
        self.recepcionar(
            registro, self.Justificacion.EN_TRAMITE, nro_formulario="F-1"
        )
        actualizado = self.recepcionar(
            registro, self.Justificacion.JUSTIFICADA, nro_formulario="F-1"
        )
        self.assertEqual(
            actualizado.estado_justificacion, self.Justificacion.JUSTIFICADA
        )

    def test_justificada_es_un_estado_final(self):
        registro = self.inasistencia()
        self.recepcionar(
            registro, self.Justificacion.JUSTIFICADA, nro_formulario="F-1"
        )
        for estado in (
            self.Justificacion.INJUSTIFICADA,
            self.Justificacion.EN_TRAMITE,
            self.Justificacion.JUSTIFICADA,
        ):
            with self.assertRaises(ValidationError):
                self.recepcionar(
                    registro,
                    estado,
                    nro_formulario="F-2",
                    motivo="Motivo suficientemente largo",
                )

    def test_no_se_puede_pasar_de_injustificada_a_injustificada(self):
        registro = self.inasistencia()
        with self.assertRaises(ValidationError):
            self.recepcionar(
                registro,
                self.Justificacion.INJUSTIFICADA,
                motivo="Motivo suficientemente largo",
            )

    def test_rechazar_el_formulario_exige_motivo_y_limpia_los_datos(self):
        registro = self.inasistencia()
        self.recepcionar(
            registro, self.Justificacion.EN_TRAMITE, nro_formulario="F-1"
        )

        with self.assertRaises(ValidationError):
            self.recepcionar(
                registro, self.Justificacion.INJUSTIFICADA, motivo="corto"
            )

        actualizado = self.recepcionar(
            registro,
            self.Justificacion.INJUSTIFICADA,
            motivo="El certificado médico no corresponde",
        )
        self.assertEqual(
            actualizado.estado_justificacion, self.Justificacion.INJUSTIFICADA
        )
        self.assertEqual(actualizado.nro_formulario, "")
        self.assertIsNone(actualizado.fecha_recepcion)
        self.assertIsNone(actualizado.recepcionado_por)

    def test_un_presente_no_admite_formulario(self):
        registro = self.guardar()
        with self.assertRaises(ValidationError):
            self.recepcionar(
                registro, self.Justificacion.EN_TRAMITE, nro_formulario="F-1"
            )

    def test_un_estado_invalido_se_rechaza(self):
        registro = self.inasistencia()
        with self.assertRaises(ValidationError):
            self.recepcionar(registro, "INVENTADO", nro_formulario="F-1")

    def test_un_periodo_cerrado_impide_recepcionar(self):
        registro = self.inasistencia()
        validar_asistencia(
            usuario=self.usuario, token=self.token, registro_id=registro.pk
        )
        cerrar_mes(usuario=self.usuario, token=self.token, anio=2026, mes=9)
        with self.assertRaises(ValidationError):
            self.recepcionar(
                registro, self.Justificacion.EN_TRAMITE, nro_formulario="F-1"
            )

    def test_la_recepcion_queda_auditada(self):
        registro = self.inasistencia()
        self.recepcionar(
            registro, self.Justificacion.EN_TRAMITE, nro_formulario="F-9"
        )
        evento = EventoAsistencia.objects.get(
            asistencia=registro, accion=EventoAsistencia.Accion.RECEPCIONAR
        )
        self.assertEqual(evento.usuario, self.usuario)
        self.assertEqual(evento.antes["estado_justificacion"], "INJUSTIFICADA")
        self.assertEqual(evento.despues["estado_justificacion"], "EN_TRAMITE")
        self.assertEqual(evento.despues["nro_formulario"], "F-9")

    def test_sin_sesion_de_edicion_se_deniega(self):
        registro = self.inasistencia()
        with self.assertRaises(PermissionDenied):
            recepcionar_formulario(
                usuario=self.usuario,
                token=str(uuid.uuid4()),
                registro_id=registro.pk,
                nuevo_estado=self.Justificacion.EN_TRAMITE,
                nro_formulario="F-1",
            )

    def test_cambiar_la_marca_a_presente_descarta_el_formulario(self):
        registro = self.inasistencia()
        self.recepcionar(
            registro, self.Justificacion.EN_TRAMITE, nro_formulario="F-1"
        )
        actualizado = guardar_asistencia(
            usuario=self.usuario,
            token=self.token,
            datos={
                "designacion": self.designacion,
                "fecha": LUNES,
                "marca": self.marca_p,
                "horas_inasistidas": Decimal("0"),
                "licencia": None,
                "observaciones": "",
            },
            registro_id=registro.pk,
        )
        self.assertEqual(
            actualizado.estado_justificacion, self.Justificacion.NO_APLICA
        )
        self.assertEqual(actualizado.nro_formulario, "")

    def test_cambiar_la_marca_a_inasistencia_la_deja_injustificada(self):
        registro = self.guardar()
        actualizado = guardar_asistencia(
            usuario=self.usuario,
            token=self.token,
            datos={
                "designacion": self.designacion,
                "fecha": LUNES,
                "marca": self.marca_i,
                "horas_inasistidas": Decimal("2"),
                "licencia": None,
                "observaciones": "",
            },
            registro_id=registro.pk,
        )
        self.assertEqual(
            actualizado.estado_justificacion, self.Justificacion.INJUSTIFICADA
        )

    def test_la_base_exige_el_formulario_en_tramite_y_justificada(self):
        registro = self.inasistencia()
        with self.assertRaises(IntegrityError), transaction.atomic():
            RegistroAsistencia.objects.filter(pk=registro.pk).update(
                estado_justificacion=self.Justificacion.EN_TRAMITE,
                nro_formulario="",
            )

    def test_la_migracion_de_datos_marca_las_inasistencias_existentes(self):
        modulo = importlib.import_module(
            "asistencias.migrations.0006_estado_justificacion_inicial"
        )
        inasistencia = RegistroAsistencia.objects.create(
            designacion=self.designacion,
            fecha=LUNES,
            marca=self.marca_i,
            horas_inasistidas=Decimal("4"),
        )
        presente = RegistroAsistencia.objects.create(
            designacion=self.designacion,
            fecha=MARTES,
            marca=self.marca_p,
        )
        modulo.marcar_inasistencias_injustificadas(django_apps, None)
        inasistencia.refresh_from_db()
        presente.refresh_from_db()
        self.assertEqual(
            inasistencia.estado_justificacion, self.Justificacion.INJUSTIFICADA
        )
        self.assertEqual(
            presente.estado_justificacion, self.Justificacion.NO_APLICA
        )


class RecepcionFormulariosVistasTests(BaseAsistenciaTests):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)
        self.inasistencia = self.guardar(
            marca=self.marca_i, horas_inasistidas=Decimal("4")
        )
        self.presente = self.guardar(fecha=MARTES)

    def test_la_lista_muestra_solo_inasistencias_pendientes(self):
        respuesta = self.client.get(reverse("asistencia:recepcion_formularios"))
        registros = list(respuesta.context["pagina"])
        self.assertEqual(registros, [self.inasistencia])

    def test_la_lista_puede_filtrar_por_justificadas(self):
        recepcionar_formulario(
            usuario=self.usuario,
            token=self.token,
            registro_id=self.inasistencia.pk,
            nuevo_estado="JUSTIFICADA",
            nro_formulario="F-1",
        )
        pendientes = self.client.get(reverse("asistencia:recepcion_formularios"))
        self.assertEqual(list(pendientes.context["pagina"]), [])

        justificadas = self.client.get(
            reverse("asistencia:recepcion_formularios"),
            {"estado_justificacion": "JUSTIFICADA"},
        )
        self.assertEqual(
            list(justificadas.context["pagina"]), [self.inasistencia]
        )

        todas = self.client.get(
            reverse("asistencia:recepcion_formularios"),
            {"estado_justificacion": "TODAS"},
        )
        self.assertEqual(list(todas.context["pagina"]), [self.inasistencia])

    def test_la_pantalla_de_recepcion_se_muestra(self):
        respuesta = self.client.get(
            reverse("asistencia:recepcionar_formulario", args=[self.inasistencia.pk])
        )
        self.assertContains(respuesta, "Recepcionar formulario")
        opciones = [
            valor
            for valor, _ in respuesta.context["form"]
            .fields["estado_justificacion"]
            .choices
        ]
        self.assertEqual(opciones, ["EN_TRAMITE", "JUSTIFICADA"])

    def test_recepcionar_por_la_pantalla(self):
        respuesta = self.client.post(
            reverse("asistencia:recepcionar_formulario", args=[self.inasistencia.pk]),
            {
                "estado_justificacion": "EN_TRAMITE",
                "nro_formulario": "F-77",
                "fecha_recepcion": LUNES.isoformat(),
                "motivo": "",
            },
        )
        self.assertRedirects(
            respuesta, reverse("asistencia:recepcion_formularios")
        )
        self.inasistencia.refresh_from_db()
        self.assertEqual(self.inasistencia.estado_justificacion, "EN_TRAMITE")
        self.assertEqual(self.inasistencia.nro_formulario, "F-77")

    def test_la_pantalla_pide_el_numero_de_formulario(self):
        respuesta = self.client.post(
            reverse("asistencia:recepcionar_formulario", args=[self.inasistencia.pk]),
            {"estado_justificacion": "EN_TRAMITE", "nro_formulario": ""},
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("nro_formulario", respuesta.context["form"].errors)
        self.inasistencia.refresh_from_db()
        self.assertEqual(self.inasistencia.estado_justificacion, "INJUSTIFICADA")

    def test_una_justificada_ya_no_admite_cambios_en_la_pantalla(self):
        recepcionar_formulario(
            usuario=self.usuario,
            token=self.token,
            registro_id=self.inasistencia.pk,
            nuevo_estado="JUSTIFICADA",
            nro_formulario="F-1",
        )
        respuesta = self.client.get(
            reverse("asistencia:recepcionar_formulario", args=[self.inasistencia.pk])
        )
        self.assertContains(respuesta, "no admite más cambios")

    def test_el_historial_filtra_por_estado_de_justificacion(self):
        respuesta = self.client.get(
            reverse("asistencia:historial"),
            {"estado_justificacion": "INJUSTIFICADA"},
        )
        self.assertEqual(list(respuesta.context["pagina"]), [self.inasistencia])

    def test_el_detalle_muestra_la_justificacion(self):
        respuesta = self.client.get(
            reverse("asistencia:detalle_asistencia", args=[self.inasistencia.pk])
        )
        self.assertContains(respuesta, "Injustificada")
        self.assertContains(respuesta, "Recepcionar formulario")


class PermisosServiciosTests(BaseAsistenciaTests):
    """Cada servicio exige su permiso, sin importar qué perfil lo otorgue."""

    def test_el_receptor_de_migracion_es_idempotente(self):
        from .signals import crear_control_concurrencia

        configuracion = django_apps.get_app_config("asistencias")
        crear_control_concurrencia(configuracion, using="default")
        crear_control_concurrencia(configuracion, using="default")
        self.assertEqual(ControlConcurrencia.objects.count(), 1)

    def test_el_receptor_de_migracion_ignora_a_las_otras_apps(self):
        from .signals import crear_control_concurrencia

        ControlConcurrencia.objects.all().delete()
        crear_control_concurrencia(
            django_apps.get_app_config("personal"), using="default"
        )
        self.assertFalse(ControlConcurrencia.objects.exists())

    def test_un_usuario_sin_permisos_no_puede_operar(self):
        sin_rol = crear_usuario("sinrol")
        token = self.abrir_sesion(sin_rol)
        with self.assertRaises(PermissionDenied):
            guardar_asistencia(
                usuario=sin_rol,
                token=token,
                datos={
                    "designacion": self.designacion,
                    "fecha": LUNES,
                    "marca": self.marca_p,
                },
            )

    def test_quien_solo_carga_corrige_y_recepciona_pero_no_valida_ni_cierra(self):
        bedel = crear_usuario("bedel", PERMISOS_CARGA)
        token = self.abrir_sesion(bedel)

        registro = guardar_asistencia(
            usuario=bedel,
            token=token,
            datos={
                "designacion": self.designacion,
                "fecha": LUNES,
                "marca": self.marca_p,
                "horas_inasistidas": Decimal("0"),
                "licencia": None,
                "observaciones": "",
            },
        )
        guardar_asistencia(
            usuario=bedel,
            token=token,
            datos={
                "designacion": self.designacion,
                "fecha": LUNES,
                "marca": self.marca_i,
                "horas_inasistidas": Decimal("2"),
                "licencia": None,
                "observaciones": "",
            },
            registro_id=registro.pk,
        )
        recepcionar_formulario(
            usuario=bedel,
            token=token,
            registro_id=registro.pk,
            nuevo_estado="EN_TRAMITE",
            nro_formulario="F-1",
        )

        with self.assertRaises(PermissionDenied):
            validar_asistencia(usuario=bedel, token=token, registro_id=registro.pk)
        with self.assertRaises(PermissionDenied):
            cerrar_mes(usuario=bedel, token=token, anio=2026, mes=9)

    def test_los_servicios_exigen_su_permiso(self):
        sin_rol = crear_usuario("sinrol")
        registro = self.guardar()
        token = self.abrir_sesion(sin_rol)
        with self.assertRaises(PermissionDenied):
            recepcionar_formulario(
                usuario=sin_rol,
                token=token,
                registro_id=registro.pk,
                nuevo_estado="EN_TRAMITE",
                nro_formulario="F-1",
            )
        with self.assertRaises(PermissionDenied):
            cerrar_dia(usuario=sin_rol, token=token, fecha=LUNES)


class PermisosVistasTests(BaseAsistenciaTests):
    def setUp(self):
        super().setUp()
        self.registro = self.guardar(
            marca=self.marca_i, horas_inasistidas=Decimal("2")
        )

    def entrar_como(self, permisos=()):
        usuario = crear_usuario("visita", permisos)
        self.client.force_login(usuario)
        return usuario

    def test_sin_permisos_las_vistas_de_escritura_responden_403(self):
        self.entrar_como()
        for url in (
            reverse("asistencia:crear_asistencia"),
            reverse("asistencia:editar_asistencia", args=[self.registro.pk]),
            reverse("asistencia:recepcionar_formulario", args=[self.registro.pk]),
            reverse("asistencia:confirmar_cierre"),
        ):
            self.assertEqual(self.client.get(url).status_code, 403, url)

        for url in (
            reverse("asistencia:validar_registro", args=[self.registro.pk]),
            reverse("asistencia:cerrar_jornada"),
        ):
            self.assertEqual(self.client.post(url).status_code, 403, url)

    def test_quien_solo_carga_no_puede_validar_ni_cerrar_periodos(self):
        self.entrar_como(PERMISOS_CARGA)
        self.assertEqual(
            self.client.post(
                reverse("asistencia:validar_registro", args=[self.registro.pk])
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("asistencia:confirmar_cierre")).status_code,
            403,
        )

    def test_quien_carga_puede_cargar_y_recepcionar(self):
        self.entrar_como(PERMISOS_CARGA)
        self.assertEqual(
            self.client.get(reverse("asistencia:crear_asistencia")).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                reverse("asistencia:recepcionar_formulario", args=[self.registro.pk])
            ).status_code,
            200,
        )

    def urls_de_lectura(self):
        return (
            reverse("asistencia:registro_diario"),
            reverse("asistencia:historial"),
            reverse("asistencia:detalle_asistencia", args=[self.registro.pk]),
            reverse("asistencia:recepcion_formularios"),
            reverse("asistencia:lista_cierres"),
        )

    def test_sin_permiso_de_lectura_las_consultas_responden_403(self):
        self.entrar_como()
        for url in self.urls_de_lectura():
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_un_anonimo_es_enviado_al_login_en_las_consultas(self):
        for url in self.urls_de_lectura():
            respuesta = self.client.get(url)
            self.assertEqual(respuesta.status_code, 302, url)
            self.assertIn("login", respuesta.url, url)

    def test_con_permiso_de_lectura_las_consultas_responden_200(self):
        self.entrar_como(PERMISOS_LECTURA)
        for url in self.urls_de_lectura():
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_el_permiso_de_lectura_no_habilita_cargar_ni_modificar(self):
        self.entrar_como(PERMISOS_LECTURA)
        self.assertEqual(
            self.client.get(reverse("asistencia:crear_asistencia")).status_code,
            403,
        )

    def test_el_historial_oculta_validar_a_quien_no_puede_y_lo_muestra_a_quien_si(self):
        self.entrar_como(PERMISOS_CARGA)
        respuesta = self.client.get(reverse("asistencia:historial"))
        self.assertNotContains(respuesta, "Validar")
        self.assertContains(respuesta, "Editar")

        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse("asistencia:historial"))
        self.assertContains(respuesta, "Validar")

    def test_el_registro_diario_oculta_nueva_asistencia_a_quien_no_puede(self):
        self.entrar_como(PERMISOS_LECTURA)
        respuesta = self.client.get(
            reverse("asistencia:registro_diario"), {"fecha": LUNES.isoformat()}
        )
        self.assertNotContains(respuesta, "Nueva asistencia")

    def test_el_admin_no_permite_editar_registros(self):
        from django.contrib import admin
        from django.test import RequestFactory

        peticion = RequestFactory().get("/")
        peticion.user = User.objects.create_superuser("root")
        modelo_admin = admin.site._registry[RegistroAsistencia]
        self.assertFalse(modelo_admin.has_add_permission(peticion))
        self.assertFalse(modelo_admin.has_change_permission(peticion))
        self.assertFalse(modelo_admin.has_delete_permission(peticion))


class CalendarioServicioTests(BaseAsistenciaTests):
    """RF-10: el calendario escolar se administra desde el sistema."""

    OCTUBRE = date(2026, 10, 12)

    def setUp(self):
        super().setUp()
        self.gestor = crear_usuario("gestor", PERMISOS_CALENDARIO)

    def cargar(self, fecha=MARTES, **datos):
        return guardar_dia_no_laborable(
            usuario=self.gestor,
            datos={
                "fecha": fecha,
                "tipo": DiaNoLaborable.Tipo.FERIADO,
                "descripcion": "Feriado de prueba",
                **datos,
            },
        )

    def cerrar_septiembre(self):
        cerrar_mes(usuario=self.usuario, token=self.token, anio=2026, mes=9)

    def test_un_dia_cargado_deja_de_ser_laborable(self):
        self.cargar(MARTES)

        self.assertIn("feriado", motivo_dia_no_laborable(MARTES))
        with self.assertRaises(ValidationError):
            self.guardar(fecha=MARTES)

    def test_modificar_cambia_el_tipo_y_la_descripcion(self):
        dia = self.cargar(MARTES)

        guardar_dia_no_laborable(
            usuario=self.gestor,
            datos={
                "fecha": MARTES,
                "tipo": DiaNoLaborable.Tipo.ASUETO,
                "descripcion": "Asueto de prueba",
            },
            dia_id=dia.pk,
        )

        dia.refresh_from_db()
        self.assertEqual(dia.tipo, DiaNoLaborable.Tipo.ASUETO)
        self.assertEqual(dia.descripcion, "Asueto de prueba")
        self.assertEqual(DiaNoLaborable.objects.count(), 1)

    def test_eliminar_un_dia_vuelve_a_habilitar_la_fecha(self):
        dia = self.cargar(MARTES)

        eliminar_dia_no_laborable(usuario=self.gestor, dia_id=dia.pk)

        self.assertIsNone(motivo_dia_no_laborable(MARTES))
        self.guardar(fecha=MARTES)

    def test_cada_operacion_exige_su_permiso(self):
        dia = self.cargar(MARTES)
        sin_permiso = crear_usuario("sin_permiso")

        with self.assertRaises(PermissionDenied):
            guardar_dia_no_laborable(
                usuario=sin_permiso,
                datos={"fecha": LUNES, "tipo": "FERIADO"},
            )
        with self.assertRaises(PermissionDenied):
            guardar_dia_no_laborable(
                usuario=sin_permiso,
                datos={"fecha": MARTES, "tipo": "ASUETO"},
                dia_id=dia.pk,
            )
        with self.assertRaises(PermissionDenied):
            eliminar_dia_no_laborable(usuario=sin_permiso, dia_id=dia.pk)

        dia.refresh_from_db()
        self.assertEqual(dia.tipo, DiaNoLaborable.Tipo.FERIADO)

    def test_un_dia_inexistente_da_un_error_de_validacion(self):
        with self.assertRaises(ValidationError):
            guardar_dia_no_laborable(
                usuario=self.gestor,
                datos={"fecha": MARTES, "tipo": "FERIADO"},
                dia_id=99999,
            )
        with self.assertRaises(ValidationError):
            eliminar_dia_no_laborable(usuario=self.gestor, dia_id=99999)

    def test_no_se_carga_un_dia_en_un_periodo_cerrado(self):
        self.cerrar_septiembre()

        with self.assertRaises(ValidationError):
            self.cargar(MARTES)
        self.assertFalse(DiaNoLaborable.objects.exists())

    def test_no_se_modifica_ni_se_elimina_un_dia_de_un_periodo_cerrado(self):
        dia = self.cargar(MARTES)
        self.cerrar_septiembre()

        with self.assertRaises(ValidationError):
            guardar_dia_no_laborable(
                usuario=self.gestor,
                datos={"fecha": MARTES, "tipo": "ASUETO"},
                dia_id=dia.pk,
            )
        # Tampoco sirve moverlo a un mes abierto: sale de uno cerrado.
        with self.assertRaises(ValidationError):
            guardar_dia_no_laborable(
                usuario=self.gestor,
                datos={"fecha": self.OCTUBRE, "tipo": "FERIADO"},
                dia_id=dia.pk,
            )
        with self.assertRaises(ValidationError):
            eliminar_dia_no_laborable(usuario=self.gestor, dia_id=dia.pk)

        dia.refresh_from_db()
        self.assertEqual(dia.fecha, MARTES)
        self.assertEqual(dia.tipo, DiaNoLaborable.Tipo.FERIADO)

    def test_no_se_mueve_un_dia_hacia_un_periodo_cerrado(self):
        dia = self.cargar(self.OCTUBRE)
        self.cerrar_septiembre()

        with self.assertRaises(ValidationError):
            guardar_dia_no_laborable(
                usuario=self.gestor,
                datos={"fecha": MARTES, "tipo": "FERIADO"},
                dia_id=dia.pk,
            )

        dia.refresh_from_db()
        self.assertEqual(dia.fecha, self.OCTUBRE)

    def test_cuenta_los_registros_ya_cargados_en_la_fecha(self):
        self.assertEqual(registros_cargados(LUNES), 0)
        self.guardar(fecha=LUNES)
        self.assertEqual(registros_cargados(LUNES), 1)
        self.assertEqual(registros_cargados(MARTES), 0)


class CalendarioVistasTests(BaseAsistenciaTests):
    def setUp(self):
        super().setUp()
        self.dia = DiaNoLaborable.objects.create(
            fecha=MARTES, descripcion="Feriado de prueba"
        )
        self.gestor = crear_usuario(
            "gestor", PERMISOS_LECTURA + PERMISOS_CALENDARIO
        )
        self.client.force_login(self.gestor)
        self.lista = reverse("asistencia:lista_calendario")

    def datos(self, **cambios):
        datos = {
            "fecha": "2026-10-12",
            "tipo": "FERIADO",
            "descripcion": "Feriado nuevo",
        }
        datos.update(cambios)
        return datos

    def mensajes(self, respuesta):
        return [str(m) for m in get_messages(respuesta.wsgi_request)]

    def test_la_lista_muestra_los_dias_del_anio(self):
        respuesta = self.client.get(self.lista, {"anio": "2026"})

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Feriado de prueba")
        self.assertContains(respuesta, "15/09/2026")

    def test_la_lista_solo_muestra_el_anio_pedido(self):
        DiaNoLaborable.objects.create(
            fecha=date(2027, 5, 25), descripcion="Otro año"
        )

        respuesta = self.client.get(self.lista, {"anio": "2026"})

        self.assertNotContains(respuesta, "Otro año")

    def test_un_anio_mal_formado_no_da_error_500(self):
        actual = timezone.localdate().year

        for valor in ("abc", "1500", "99999999999999999999", ""):
            respuesta = self.client.get(self.lista, {"anio": valor})
            self.assertEqual(respuesta.status_code, 200, valor)
            self.assertEqual(respuesta.context["anio"], actual, valor)

    def test_la_consulta_exige_el_permiso_de_lectura(self):
        self.client.force_login(crear_usuario("sinrol"))
        self.assertEqual(self.client.get(self.lista).status_code, 403)

        self.client.logout()
        respuesta = self.client.get(self.lista)
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn("login", respuesta.url)

    def test_quien_solo_consulta_no_ve_las_acciones(self):
        self.client.force_login(crear_usuario("lector", PERMISOS_LECTURA))

        respuesta = self.client.get(self.lista, {"anio": "2026"})

        self.assertContains(respuesta, "Feriado de prueba")
        self.assertNotContains(respuesta, "Nuevo día")
        self.assertNotContains(
            respuesta,
            reverse("asistencia:editar_dia_no_laborable", args=[self.dia.pk]),
        )
        self.assertNotContains(
            respuesta,
            reverse("asistencia:eliminar_dia_no_laborable", args=[self.dia.pk]),
        )

    def test_el_registro_diario_enlaza_al_calendario(self):
        respuesta = self.client.get(reverse("asistencia:registro_diario"))
        self.assertContains(respuesta, self.lista)

    def test_cargar_un_dia(self):
        respuesta = self.client.post(
            reverse("asistencia:crear_dia_no_laborable"), self.datos()
        )

        self.assertRedirects(respuesta, f"{self.lista}?anio=2026")
        self.assertTrue(
            DiaNoLaborable.objects.filter(
                fecha=date(2026, 10, 12), descripcion="Feriado nuevo"
            ).exists()
        )

    def test_una_fecha_repetida_se_informa_en_el_formulario(self):
        respuesta = self.client.post(
            reverse("asistencia:crear_dia_no_laborable"),
            self.datos(fecha=MARTES.isoformat()),
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Ya hay un día cargado en esa fecha.")
        self.assertEqual(DiaNoLaborable.objects.count(), 1)

    def test_un_anio_fuera_de_rango_se_rechaza(self):
        respuesta = self.client.post(
            reverse("asistencia:crear_dia_no_laborable"),
            self.datos(fecha="1999-12-25"),
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "El año debe estar entre 2000 y 2100.")
        self.assertEqual(DiaNoLaborable.objects.count(), 1)

    def test_cargar_en_un_periodo_cerrado_se_informa_sin_guardar(self):
        cerrar_mes(usuario=self.usuario, token=self.token, anio=2026, mes=9)

        respuesta = self.client.post(
            reverse("asistencia:crear_dia_no_laborable"),
            self.datos(fecha="2026-09-16"),
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(
            any("período está cerrado" in t for t in self.mensajes(respuesta))
        )
        self.assertEqual(DiaNoLaborable.objects.count(), 1)

    def test_avisa_si_ya_habia_asistencias_cargadas_ese_dia(self):
        self.guardar(fecha=LUNES)

        respuesta = self.client.post(
            reverse("asistencia:crear_dia_no_laborable"),
            self.datos(fecha=LUNES.isoformat()),
        )

        self.assertRedirects(respuesta, f"{self.lista}?anio=2026")
        self.assertTrue(
            any("registro(s) de asistencia" in t for t in self.mensajes(respuesta))
        )

    def test_el_formulario_de_edicion_muestra_la_fecha_cargada(self):
        respuesta = self.client.get(
            reverse("asistencia:editar_dia_no_laborable", args=[self.dia.pk])
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'value="2026-09-15"')

    def test_editar_un_dia(self):
        respuesta = self.client.post(
            reverse("asistencia:editar_dia_no_laborable", args=[self.dia.pk]),
            self.datos(
                fecha=MARTES.isoformat(),
                tipo="ASUETO",
                descripcion="Asueto editado",
            ),
        )

        self.assertRedirects(respuesta, f"{self.lista}?anio=2026")
        self.dia.refresh_from_db()
        self.assertEqual(self.dia.tipo, "ASUETO")
        self.assertEqual(self.dia.descripcion, "Asueto editado")

    def test_editar_un_dia_inexistente_responde_404(self):
        respuesta = self.client.get(
            reverse("asistencia:editar_dia_no_laborable", args=[99999])
        )
        self.assertEqual(respuesta.status_code, 404)

    def test_eliminar_un_dia(self):
        respuesta = self.client.post(
            reverse("asistencia:eliminar_dia_no_laborable", args=[self.dia.pk])
        )

        self.assertRedirects(respuesta, f"{self.lista}?anio=2026")
        self.assertFalse(DiaNoLaborable.objects.exists())

    def test_eliminar_solo_acepta_post(self):
        respuesta = self.client.get(
            reverse("asistencia:eliminar_dia_no_laborable", args=[self.dia.pk])
        )

        self.assertEqual(respuesta.status_code, 405)
        self.assertTrue(DiaNoLaborable.objects.exists())

    def test_eliminar_un_dia_inexistente_se_informa_sin_error_500(self):
        respuesta = self.client.post(
            reverse("asistencia:eliminar_dia_no_laborable", args=[99999])
        )

        self.assertRedirects(respuesta, self.lista)
        self.assertTrue(
            any("no existe" in t for t in self.mensajes(respuesta))
        )

    def test_las_acciones_de_escritura_exigen_su_permiso(self):
        self.client.force_login(crear_usuario("lector", PERMISOS_LECTURA))

        self.assertEqual(
            self.client.get(
                reverse("asistencia:crear_dia_no_laborable")
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("asistencia:crear_dia_no_laborable"), self.datos()
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                reverse("asistencia:editar_dia_no_laborable", args=[self.dia.pk])
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("asistencia:eliminar_dia_no_laborable", args=[self.dia.pk])
            ).status_code,
            403,
        )
        self.assertEqual(DiaNoLaborable.objects.count(), 1)


class RobustezTests(BaseAsistenciaTests):
    """Entradas hostiles y defectos que antes terminaban en error 500."""

    LARGO = "m" * 600

    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)

    def datos(self, **cambios):
        datos = {
            "designacion": self.designacion,
            "fecha": LUNES,
            "marca": self.marca_p,
            "horas_inasistidas": Decimal("0"),
            "licencia": None,
            "observaciones": "",
        }
        datos.update(cambios)
        return datos

    def mensajes(self, respuesta):
        return [str(m) for m in get_messages(respuesta.wsgi_request)]

    def jefa(self):
        jefa = User.objects.create_superuser("jefa")
        token = str(uuid.uuid4())
        adquirir_sesion_edicion(jefa, token)
        return jefa, token

    # ───────────── motivo más largo que la columna ─────────────
    def test_un_motivo_demasiado_largo_no_deja_dar_de_alta(self):
        with self.assertRaises(ValidationError):
            guardar_asistencia(
                usuario=self.usuario,
                token=self.token,
                datos=self.datos(),
                motivo=self.LARGO,
            )
        self.assertFalse(RegistroAsistencia.objects.exists())

    def test_un_motivo_demasiado_largo_se_informa_al_editar_desde_la_vista(self):
        registro = self.guardar()

        respuesta = self.client.post(
            reverse("asistencia:editar_asistencia", args=[registro.pk]),
            {
                "designacion": self.designacion.pk,
                "fecha": LUNES.isoformat(),
                "marca": self.marca_p.pk,
                "horas_inasistidas": "0",
                "observaciones": "cambio",
                "motivo": self.LARGO,
            },
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(any("no puede superar" in t for t in self.mensajes(respuesta)))
        registro.refresh_from_db()
        self.assertEqual(registro.observaciones, "")

    def test_un_motivo_demasiado_largo_se_rechaza_en_la_planilla(self):
        with self.assertRaises(ValidationError):
            guardar_planilla(
                usuario=self.usuario,
                token=self.token,
                fecha=LUNES,
                filas=[self.datos()],
                motivo=self.LARGO,
            )
        self.assertFalse(RegistroAsistencia.objects.exists())

    def test_la_recepcion_valida_el_largo_del_motivo_y_del_formulario(self):
        registro = self.guardar(marca=self.marca_i, horas_inasistidas=Decimal("2"))

        with self.assertRaises(ValidationError):
            recepcionar_formulario(
                usuario=self.usuario,
                token=self.token,
                registro_id=registro.pk,
                nuevo_estado=RegistroAsistencia.EstadoJustificacion.EN_TRAMITE,
                nro_formulario="F-1",
                motivo=self.LARGO,
            )
        with self.assertRaises(ValidationError):
            recepcionar_formulario(
                usuario=self.usuario,
                token=self.token,
                registro_id=registro.pk,
                nuevo_estado=RegistroAsistencia.EstadoJustificacion.EN_TRAMITE,
                nro_formulario="F" * 31,
            )

    def test_la_reapertura_valida_el_largo_del_motivo(self):
        jefa, token = self.jefa()
        cerrar_mes(usuario=jefa, token=token, anio=2026, mes=9)

        with self.assertRaises(ValidationError):
            reabrir_mes(
                usuario=jefa, token=token, anio=2026, mes=9, motivo=self.LARGO
            )

    def test_reabrir_un_periodo_inexistente_da_un_error_de_validacion(self):
        jefa, token = self.jefa()

        with self.assertRaises(ValidationError):
            reabrir_mes(
                usuario=jefa,
                token=token,
                anio=2030,
                mes=1,
                motivo="motivo suficientemente largo",
            )

    # ───────────── planilla con dígitos que no son números ─────────────
    def test_la_planilla_ignora_los_digitos_que_int_no_convierte(self):
        for datos in (
            {"marca-²": "1"},
            {f"marca-{self.designacion.pk}": "²"},
            {
                f"marca-{self.designacion.pk}": str(self.marca_p.pk),
                f"licencia-{self.designacion.pk}": "²",
            },
        ):
            respuesta = self.client.post(
                reverse("asistencia:planilla_rapida"),
                {"fecha": LUNES.isoformat(), **datos},
            )
            self.assertEqual(respuesta.status_code, 200, datos)

        self.assertFalse(RegistroAsistencia.objects.exists())

    # ───────────── consultas repetidas (N+1) ─────────────
    def test_el_registro_diario_no_hace_una_consulta_por_registro(self):
        carrera = Carrera.objects.create(nombre="Carrera de prueba")

        def agregar(desde, hasta):
            for i in range(desde, hasta):
                persona = Persona.objects.create(
                    dni=f"4000{i:04d}", apellido_nombre=f"APELLIDO{i}, N", sexo="M"
                )
                espacio = EspacioCurricular.objects.create(
                    nombre=f"Materia {i}", carrera=carrera
                )
                designacion = Designacion.objects.create(
                    persona=persona,
                    cargo=self.cargo,
                    espacio_curricular=espacio,
                    desde=date(2026, 3, 1),
                )
                self.guardar(designacion=designacion)

        url = f"{reverse('asistencia:registro_diario')}?fecha={LUNES.isoformat()}"

        agregar(0, 2)
        with CaptureQueriesContext(connection) as pocas:
            self.client.get(url)

        agregar(2, 10)
        with CaptureQueriesContext(connection) as muchas:
            respuesta = self.client.get(url)

        self.assertContains(respuesta, "Materia 9")
        self.assertEqual(len(pocas), len(muchas))

    # ───────────── cerrar sesión libera el lugar de edición ─────────────
    def test_al_cerrar_sesion_se_libera_el_lugar_de_edicion(self):
        token = str(uuid.uuid4())
        sesion = self.client.session
        sesion["asistencia_token"] = token
        sesion.save()
        adquirir_sesion_edicion(self.usuario, token)

        self.client.logout()

        self.assertFalse(SesionEdicion.objects.get(token=token).activa)

    def test_cerrar_sesion_sin_sesion_de_edicion_no_falla(self):
        self.client.logout()
        self.client.logout()

    # ───────────── el admin no saltea los cierres ─────────────
    def test_el_admin_de_cierres_mensuales_es_solo_consulta(self):
        from django.contrib import admin
        from django.test import RequestFactory

        peticion = RequestFactory().get("/")
        peticion.user = User.objects.create_superuser("root")
        modelo_admin = admin.site._registry[CierreMensual]

        self.assertFalse(modelo_admin.has_add_permission(peticion))
        self.assertFalse(modelo_admin.has_change_permission(peticion))
        self.assertFalse(modelo_admin.has_delete_permission(peticion))


class ValidarRegistroTests(BaseAsistenciaTests):
    """Validar un registro inexistente o ya validado no debe dar error 500."""

    def setUp(self):
        super().setUp()
        self.registro = self.guardar()

    def validar(self, registro_id):
        return validar_asistencia(
            usuario=self.usuario, token=self.token, registro_id=registro_id
        )

    def test_un_registro_inexistente_da_un_error_de_validacion(self):
        with self.assertRaises(ValidationError):
            self.validar(99999)

    def test_un_registro_ya_validado_no_genera_otro_evento(self):
        self.validar(self.registro.pk)
        with self.assertRaises(ValidationError):
            self.validar(self.registro.pk)
        self.assertEqual(
            EventoAsistencia.objects.filter(
                asistencia=self.registro,
                accion=EventoAsistencia.Accion.VALIDAR,
            ).count(),
            1,
        )

    def test_la_vista_informa_un_registro_inexistente_sin_error_500(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.post(
            reverse("asistencia:validar_registro", args=[99999])
        )
        self.assertRedirects(
            respuesta,
            reverse("asistencia:historial"),
        )
        textos = [str(m) for m in get_messages(respuesta.wsgi_request)]
        self.assertTrue(any("no existe" in t for t in textos))

    def test_la_vista_informa_un_registro_ya_validado(self):
        self.validar(self.registro.pk)
        self.client.force_login(self.usuario)
        respuesta = self.client.post(
            reverse("asistencia:validar_registro", args=[self.registro.pk])
        )
        self.assertRedirects(respuesta, reverse("asistencia:historial"))
        textos = [str(m) for m in get_messages(respuesta.wsgi_request)]
        self.assertTrue(any("ya está validado" in t for t in textos))


class CierreDiarioTests(BaseAsistenciaTests):
    """RN-06: jornada cerrada, modificar requiere Secretaría o Subsecretaría."""

    def setUp(self):
        super().setUp()
        self.bedel = crear_usuario("bedel", PERMISOS_CARGA)

    def cerrar(self, fecha=LUNES):
        return cerrar_dia(usuario=self.usuario, token=self.token, fecha=fecha)

    def datos(self, **cambios):
        datos = {
            "designacion": self.designacion,
            "fecha": LUNES,
            "marca": self.marca_p,
            "horas_inasistidas": Decimal("0"),
            "licencia": None,
            "observaciones": "",
        }
        datos.update(cambios)
        return datos

    def test_cerrar_la_jornada_la_registra_y_audita(self):
        self.guardar()
        cierre = self.cerrar()
        self.assertEqual(cierre.fecha, LUNES)
        self.assertEqual(cierre.cerrado_por, self.usuario)
        evento = EventoAsistencia.objects.get(cierre_diario=cierre)
        self.assertEqual(evento.accion, EventoAsistencia.Accion.CERRAR_DIA)
        self.assertEqual(evento.despues["registros"], 1)

    def test_no_se_cierra_dos_veces_la_misma_jornada(self):
        self.cerrar()
        with self.assertRaises(ValidationError):
            self.cerrar()

    def test_no_se_cierra_una_jornada_futura(self):
        with self.assertRaises(ValidationError):
            self.cerrar(timezone.localdate() + timedelta(days=1))

    def test_no_se_cierra_un_dia_no_laborable(self):
        DiaNoLaborable.objects.create(fecha=MARTES)
        for fecha in (SABADO, MARTES):
            with self.assertRaises(ValidationError):
                self.cerrar(fecha)

    def test_no_se_cierra_la_jornada_de_un_periodo_cerrado(self):
        cerrar_mes(usuario=self.usuario, token=self.token, anio=2026, mes=9)
        with self.assertRaises(ValidationError):
            self.cerrar()

    def test_quien_carga_puede_cerrar_la_jornada(self):
        token = self.abrir_sesion(self.bedel)
        cierre = cerrar_dia(usuario=self.bedel, token=token, fecha=LUNES)
        self.assertEqual(cierre.cerrado_por, self.bedel)

    def test_quien_solo_carga_no_puede_cargar_en_una_jornada_cerrada(self):
        self.cerrar()
        token = self.abrir_sesion(self.bedel)
        with self.assertRaises(PermissionDenied) as contexto:
            guardar_asistencia(
                usuario=self.bedel,
                token=token,
                datos=self.datos(),
                motivo="Olvido de carga del día anterior",
            )
        self.assertIn("Secretaría o Subsecretaría", str(contexto.exception))
        self.assertFalse(RegistroAsistencia.objects.exists())

    def test_quien_solo_carga_no_puede_corregir_en_una_jornada_cerrada(self):
        registro = self.guardar()
        self.cerrar()
        token = self.abrir_sesion(self.bedel)
        with self.assertRaises(PermissionDenied):
            guardar_asistencia(
                usuario=self.bedel,
                token=token,
                datos=self.datos(marca=self.marca_i, horas_inasistidas=Decimal("2")),
                registro_id=registro.pk,
                motivo="Error tipográfico en la marca",
            )
        registro.refresh_from_db()
        self.assertEqual(registro.marca.codigo, "P")

    def test_con_autorizacion_se_modifica_con_motivo(self):
        registro = self.guardar()
        self.cerrar()
        actualizado = guardar_asistencia(
            usuario=self.usuario,
            token=self.token,
            datos=self.datos(marca=self.marca_i, horas_inasistidas=Decimal("2")),
            registro_id=registro.pk,
            motivo="Error tipográfico en la marca",
        )
        self.assertEqual(actualizado.marca.codigo, "I")
        evento = EventoAsistencia.objects.filter(
            asistencia=registro, accion=EventoAsistencia.Accion.EDITAR
        ).get()
        self.assertEqual(evento.motivo, "Error tipográfico en la marca")

    def test_con_autorizacion_sin_motivo_no_puede_modificar_una_jornada_cerrada(self):
        registro = self.guardar()
        self.cerrar()
        for motivo in ("", "corto"):
            with self.assertRaises(ValidationError):
                guardar_asistencia(
                    usuario=self.usuario,
                    token=self.token,
                    datos=self.datos(marca=self.marca_i, horas_inasistidas=Decimal("2")),
                    registro_id=registro.pk,
                    motivo=motivo,
                )

    def test_con_autorizacion_puede_cargar_en_una_jornada_cerrada_con_motivo(self):
        self.cerrar()
        registro = guardar_asistencia(
            usuario=self.usuario,
            token=self.token,
            datos=self.datos(),
            motivo="Carga omitida por corte de energía",
        )
        self.assertEqual(registro.fecha, LUNES)

    def test_mover_un_registro_fuera_de_una_jornada_cerrada_tambien_se_controla(self):
        registro = self.guardar()
        self.cerrar(LUNES)
        token = self.abrir_sesion(self.bedel)
        with self.assertRaises(PermissionDenied):
            guardar_asistencia(
                usuario=self.bedel,
                token=token,
                datos=self.datos(fecha=MARTES),
                registro_id=registro.pk,
                motivo="Se cargó en el día equivocado",
            )

    def test_otras_jornadas_siguen_abiertas(self):
        self.cerrar(LUNES)
        token = self.abrir_sesion(self.bedel)
        registro = guardar_asistencia(
            usuario=self.bedel,
            token=token,
            datos=self.datos(fecha=MARTES),
        )
        self.assertEqual(registro.fecha, MARTES)

    def test_una_jornada_cerrada_no_impide_validar_ni_recepcionar(self):
        registro = self.guardar(marca=self.marca_i, horas_inasistidas=Decimal("2"))
        self.cerrar()
        recepcionar_formulario(
            usuario=self.usuario,
            token=self.token,
            registro_id=registro.pk,
            nuevo_estado="EN_TRAMITE",
            nro_formulario="F-1",
        )
        validar_asistencia(
            usuario=self.usuario, token=self.token, registro_id=registro.pk
        )

    def test_la_base_impide_dos_cierres_de_la_misma_fecha(self):
        self.cerrar()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CierreDiario.objects.create(fecha=LUNES, cerrado_por=self.usuario)


class CierreDiarioVistasTests(BaseAsistenciaTests):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)

    def url_diaria(self, fecha=LUNES):
        return f"{reverse('asistencia:registro_diario')}?fecha={fecha.isoformat()}"

    def test_se_cierra_la_jornada_desde_la_pantalla(self):
        respuesta = self.client.get(self.url_diaria())
        self.assertContains(respuesta, "Cerrar jornada")

        respuesta = self.client.post(
            reverse("asistencia:cerrar_jornada"), {"fecha": LUNES.isoformat()}
        )
        self.assertRedirects(respuesta, self.url_diaria())
        self.assertTrue(CierreDiario.objects.filter(fecha=LUNES).exists())

        respuesta = self.client.get(self.url_diaria())
        self.assertContains(respuesta, "Jornada cerrada por")
        self.assertNotContains(respuesta, "Cerrar jornada</button>")

    def test_el_boton_no_aparece_en_dias_no_laborables_ni_futuros(self):
        for fecha in (SABADO, timezone.localdate() + timedelta(days=3)):
            respuesta = self.client.get(self.url_diaria(fecha))
            self.assertNotContains(respuesta, "Cerrar jornada</button>")

    def test_un_error_al_cerrar_se_informa_con_un_mensaje(self):
        respuesta = self.client.post(
            reverse("asistencia:cerrar_jornada"), {"fecha": SABADO.isoformat()}
        )
        textos = [str(m) for m in get_messages(respuesta.wsgi_request)]
        self.assertTrue(any("fin de semana" in t for t in textos))
        self.assertFalse(CierreDiario.objects.exists())

    def test_una_fecha_invalida_al_cerrar_redirige(self):
        respuesta = self.client.post(
            reverse("asistencia:cerrar_jornada"), {"fecha": "abc"}
        )
        self.assertRedirects(respuesta, reverse("asistencia:registro_diario"))

    def test_cerrar_jornada_solo_acepta_post(self):
        respuesta = self.client.get(reverse("asistencia:cerrar_jornada"))
        self.assertEqual(respuesta.status_code, 405)

    def test_quien_solo_carga_ve_un_aviso_de_permiso_en_jornada_cerrada(self):
        cerrar_dia(usuario=self.usuario, token=self.token, fecha=LUNES)
        self.client.force_login(crear_usuario("bedel", PERMISOS_CARGA))
        respuesta = self.client.post(
            reverse("asistencia:crear_asistencia"),
            {
                "designacion": self.designacion.pk,
                "fecha": LUNES.isoformat(),
                "marca": self.marca_p.pk,
                "horas_inasistidas": "0",
                "observaciones": "",
                "motivo": "Carga omitida",
            },
        )
        textos = [str(m) for m in get_messages(respuesta.wsgi_request)]
        self.assertTrue(any("Secretaría o Subsecretaría" in t for t in textos))

    def test_el_listado_de_cierres_incluye_las_jornadas(self):
        cerrar_dia(usuario=self.usuario, token=self.token, fecha=LUNES)
        respuesta = self.client.get(reverse("asistencia:lista_cierres"))
        self.assertContains(respuesta, "14/09/2026")


class BasePlanillaTests(BaseAsistenciaTests):
    """Dos docentes: PEREZ con dos designaciones y GOMEZ con una."""

    def setUp(self):
        super().setUp()
        self.perez_2 = Designacion.objects.create(
            persona=self.persona,
            cargo=self.cargo,
            desde=date(2026, 3, 1),
        )
        self.persona_2 = Persona.objects.create(
            dni="20111222",
            apellido_nombre="GOMEZ, ANA",
            sexo="F",
        )
        self.gomez = Designacion.objects.create(
            persona=self.persona_2,
            cargo=self.cargo,
            desde=date(2026, 3, 1),
        )

    def fila(self, designacion, marca=None, **cambios):
        datos = {
            "designacion": designacion,
            "marca": marca or self.marca_p,
            "horas_inasistidas": Decimal("0"),
            "licencia": None,
            "observaciones": "",
        }
        datos.update(cambios)
        return datos


class PlanillaServicioTests(BasePlanillaTests):
    """RF-07: carga de todo el día en una sola operación."""

    def guardar_planilla(self, filas, fecha=LUNES, usuario=None, token=None, **kw):
        return guardar_planilla(
            usuario=usuario or self.usuario,
            token=token or self.token,
            fecha=fecha,
            filas=filas,
            **kw,
        )

    def test_guarda_todas_las_filas_y_audita_cada_una(self):
        registros = self.guardar_planilla(
            [
                self.fila(self.gomez),
                self.fila(self.designacion),
                self.fila(
                    self.perez_2,
                    marca=self.marca_i,
                    horas_inasistidas=Decimal("3"),
                ),
            ]
        )
        self.assertEqual(len(registros), 3)
        self.assertEqual(RegistroAsistencia.objects.filter(fecha=LUNES).count(), 3)
        self.assertEqual(
            EventoAsistencia.objects.filter(
                accion=EventoAsistencia.Accion.CREAR
            ).count(),
            3,
        )

    def test_una_fila_con_error_no_guarda_ninguna(self):
        with self.assertRaises(PlanillaConErrores) as contexto:
            self.guardar_planilla(
                [
                    self.fila(self.gomez),
                    # Inasistencia sin horas.
                    self.fila(self.designacion, marca=self.marca_i),
                ]
            )
        self.assertEqual(list(contexto.exception.errores), [self.designacion.pk])
        self.assertIn("horas", contexto.exception.errores[self.designacion.pk])
        self.assertFalse(RegistroAsistencia.objects.exists())
        self.assertFalse(
            EventoAsistencia.objects.filter(
                accion=EventoAsistencia.Accion.CREAR
            ).exists()
        )

    def test_informa_los_errores_de_varias_filas_a_la_vez(self):
        with self.assertRaises(PlanillaConErrores) as contexto:
            self.guardar_planilla(
                [
                    self.fila(self.gomez, marca=self.marca_i),
                    self.fila(self.designacion, marca=self.marca_i),
                    self.fila(self.perez_2),
                ]
            )
        self.assertEqual(
            set(contexto.exception.errores),
            {self.gomez.pk, self.designacion.pk},
        )

    def test_no_permite_marcar_dos_veces_la_misma_designacion(self):
        self.guardar()
        with self.assertRaises(PlanillaConErrores) as contexto:
            self.guardar_planilla([self.fila(self.designacion)])
        self.assertIn(self.designacion.pk, contexto.exception.errores)

    def test_sin_filas_se_rechaza(self):
        with self.assertRaises(ValidationError):
            self.guardar_planilla([])

    def test_un_dia_no_laborable_se_informa_una_sola_vez(self):
        with self.assertRaises(ValidationError) as contexto:
            self.guardar_planilla([self.fila(self.gomez)], fecha=SABADO)
        self.assertIn("fin de semana", " ".join(contexto.exception.messages))

    def test_un_periodo_cerrado_se_informa_una_sola_vez(self):
        cerrar_mes(usuario=self.usuario, token=self.token, anio=2026, mes=9)
        with self.assertRaises(ValidationError):
            self.guardar_planilla([self.fila(self.gomez)])

    def test_sin_permiso_se_deniega(self):
        sin_rol = crear_usuario("sinrol")
        token = self.abrir_sesion(sin_rol)
        with self.assertRaises(PermissionDenied):
            self.guardar_planilla(
                [self.fila(self.gomez)], usuario=sin_rol, token=token
            )

    def test_quien_carga_puede_usar_la_planilla(self):
        bedel = crear_usuario("bedel", PERMISOS_CARGA)
        token = self.abrir_sesion(bedel)
        registros = self.guardar_planilla(
            [self.fila(self.gomez)], usuario=bedel, token=token
        )
        self.assertEqual(registros[0].creado_por, bedel)

    def test_en_una_jornada_cerrada_solo_con_autorizacion_y_motivo(self):
        cerrar_dia(usuario=self.usuario, token=self.token, fecha=LUNES)

        with self.assertRaises(ValidationError):
            self.guardar_planilla([self.fila(self.gomez)])

        registros = self.guardar_planilla(
            [self.fila(self.gomez)], motivo="Carga omitida por corte de energía"
        )
        self.assertEqual(len(registros), 1)

        bedel = crear_usuario("bedel", PERMISOS_CARGA)
        token = self.abrir_sesion(bedel)
        with self.assertRaises(PermissionDenied):
            self.guardar_planilla(
                [self.fila(self.designacion)],
                usuario=bedel,
                token=token,
                motivo="Carga omitida por corte de energía",
            )


class PlanillaVistasTests(BasePlanillaTests):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)
        self.url = reverse("asistencia:planilla_rapida")

    def ver(self, fecha=LUNES, **extra):
        return self.client.get(self.url, {"fecha": fecha.isoformat(), **extra})

    def enviar(self, datos, fecha=LUNES):
        return self.client.post(self.url, {"fecha": fecha.isoformat(), **datos})

    def test_muestra_una_fila_por_designacion_vigente_ordenada_por_docente(self):
        respuesta = self.ver()
        self.assertEqual(respuesta.status_code, 200)
        orden = [fila["designacion"].pk for fila in respuesta.context["filas"]]
        self.assertEqual(
            orden, [self.gomez.pk, self.designacion.pk, self.perez_2.pk]
        )
        self.assertEqual(respuesta.context["total"], 3)
        self.assertEqual(respuesta.context["pendientes"], 3)

    def test_la_primera_fila_de_cada_docente_se_marca_como_tal(self):
        filas = self.ver().context["filas"]
        self.assertEqual(
            [fila["primera_del_docente"] for fila in filas],
            [True, True, False],
        )

    def test_excluye_las_designaciones_no_vigentes_en_la_fecha(self):
        futura = Designacion.objects.create(
            persona=self.persona_2, cargo=self.cargo, desde=date(2026, 10, 1)
        )
        vencida = Designacion.objects.create(
            persona=self.persona_2,
            cargo=self.cargo,
            desde=date(2026, 3, 1),
            hasta=date(2026, 9, 11),
        )
        inactiva = Designacion.objects.create(
            persona=self.persona_2,
            cargo=self.cargo,
            desde=date(2026, 3, 1),
            activo=False,
        )
        ids = {fila["designacion"].pk for fila in self.ver().context["filas"]}
        for excluida in (futura, vencida, inactiva):
            self.assertNotIn(excluida.pk, ids)

    def test_excluye_a_las_personas_inactivas(self):
        self.persona_2.activa = False
        self.persona_2.save()
        ids = {fila["designacion"].pk for fila in self.ver().context["filas"]}
        self.assertNotIn(self.gomez.pk, ids)

    def test_las_ya_marcadas_se_muestran_sin_campos_de_carga(self):
        self.guardar()
        respuesta = self.ver()
        self.assertNotContains(respuesta, f'name="marca-{self.designacion.pk}"')
        self.assertContains(respuesta, f'name="marca-{self.gomez.pk}"')
        self.assertEqual(respuesta.context["marcadas"], 1)
        self.assertEqual(respuesta.context["pendientes"], 2)

    def test_filtra_por_apellido_o_dni(self):
        for texto in ("gomez", "20111222"):
            filas = self.ver(q=texto).context["filas"]
            self.assertEqual(
                [fila["designacion"].pk for fila in filas], [self.gomez.pk]
            )

    def test_guarda_la_planilla_y_vuelve_al_registro_diario(self):
        respuesta = self.enviar(
            {
                f"marca-{self.gomez.pk}": self.marca_p.pk,
                f"marca-{self.designacion.pk}": self.marca_i.pk,
                f"horas-{self.designacion.pk}": "2,5",
                f"obs-{self.designacion.pk}": "Aviso por teléfono",
                f"marca-{self.perez_2.pk}": "",
            }
        )
        self.assertRedirects(
            respuesta,
            f"{reverse('asistencia:registro_diario')}?fecha={LUNES.isoformat()}",
        )
        self.assertEqual(RegistroAsistencia.objects.filter(fecha=LUNES).count(), 2)
        inasistencia = RegistroAsistencia.objects.get(designacion=self.designacion)
        self.assertEqual(inasistencia.horas_inasistidas, Decimal("2.5"))
        self.assertEqual(inasistencia.observaciones, "Aviso por teléfono")
        self.assertEqual(inasistencia.estado_justificacion, "INJUSTIFICADA")

    def test_sin_marcar_nada_no_guarda(self):
        respuesta = self.enviar({f"marca-{self.gomez.pk}": ""})
        self.assertEqual(respuesta.status_code, 200)
        textos = [str(m) for m in get_messages(respuesta.wsgi_request)]
        self.assertTrue(any("ninguna asistencia" in t for t in textos))

    def test_una_fila_con_error_no_guarda_ninguna_y_conserva_lo_cargado(self):
        respuesta = self.enviar(
            {
                f"marca-{self.gomez.pk}": self.marca_p.pk,
                f"marca-{self.designacion.pk}": self.marca_i.pk,
                f"horas-{self.designacion.pk}": "0",
                f"obs-{self.designacion.pk}": "Texto que debe conservarse",
            }
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(RegistroAsistencia.objects.exists())
        fila_gomez, fila_perez = respuesta.context["filas"][:2]
        self.assertIsNone(fila_gomez["error"])
        self.assertIn("horas", fila_perez["error"])
        self.assertContains(respuesta, "Texto que debe conservarse")
        self.assertContains(respuesta, "No se guardó ninguna")

    def test_valores_no_validos_se_informan_por_fila(self):
        casos = {
            "horas": {f"horas-{self.designacion.pk}": "abc"},
            "negativas": {f"horas-{self.designacion.pk}": "-1"},
            "no finitas": {f"horas-{self.designacion.pk}": "NaN"},
        }
        for nombre, extra in casos.items():
            respuesta = self.enviar(
                {f"marca-{self.designacion.pk}": self.marca_i.pk, **extra}
            )
            fila = next(
                f
                for f in respuesta.context["filas"]
                if f["designacion"].pk == self.designacion.pk
            )
            self.assertIsNotNone(fila["error"], nombre)
            self.assertFalse(RegistroAsistencia.objects.exists(), nombre)

    def test_una_marca_fuera_del_catalogo_se_rechaza(self):
        otra = MarcaAsistencia.objects.create(codigo="XX", descripcion="Otra")
        respuesta = self.enviar({f"marca-{self.gomez.pk}": otra.pk})
        self.assertFalse(RegistroAsistencia.objects.exists())
        self.assertIsNotNone(respuesta.context["filas"][0]["error"])

    def test_ofrece_solo_las_licencias_vigentes_de_cada_designacion(self):
        propia = self.crear_licencia(desde=LUNES, hasta=None)
        respuesta = self.ver()
        por_designacion = {
            fila["designacion"].pk: fila["licencias"]
            for fila in respuesta.context["filas"]
        }
        self.assertEqual(por_designacion[self.designacion.pk], [propia])
        self.assertEqual(por_designacion[self.gomez.pk], [])

    def test_carga_una_licencia_vinculada(self):
        licencia = self.crear_licencia(desde=LUNES, hasta=None)
        self.enviar(
            {
                f"marca-{self.designacion.pk}": self.marca_lic.pk,
                f"horas-{self.designacion.pk}": "4",
                f"licencia-{self.designacion.pk}": licencia.pk,
            }
        )
        registro = RegistroAsistencia.objects.get(designacion=self.designacion)
        self.assertEqual(registro.licencia, licencia)

    def test_rechaza_una_licencia_de_otra_designacion(self):
        ajena = self.crear_licencia(desde=LUNES, hasta=None, designacion=self.gomez)
        respuesta = self.enviar(
            {
                f"marca-{self.designacion.pk}": self.marca_lic.pk,
                f"horas-{self.designacion.pk}": "4",
                f"licencia-{self.designacion.pk}": ajena.pk,
            }
        )
        self.assertFalse(RegistroAsistencia.objects.exists())
        fila = next(
            f
            for f in respuesta.context["filas"]
            if f["designacion"].pk == self.designacion.pk
        )
        self.assertIn("licencia", fila["error"].lower())

    def test_una_designacion_no_vigente_enviada_a_mano_se_rechaza(self):
        vencida = Designacion.objects.create(
            persona=self.persona_2,
            cargo=self.cargo,
            desde=date(2026, 3, 1),
            hasta=date(2026, 9, 11),
        )
        self.enviar({f"marca-{vencida.pk}": self.marca_p.pk})
        self.assertFalse(RegistroAsistencia.objects.exists())

    def test_un_fin_de_semana_bloquea_la_planilla(self):
        respuesta = self.ver(SABADO)
        self.assertContains(respuesta, "es fin de semana")
        self.assertNotContains(respuesta, "Guardar planilla")

        respuesta = self.enviar({f"marca-{self.gomez.pk}": self.marca_p.pk}, SABADO)
        self.assertFalse(RegistroAsistencia.objects.exists())
        textos = [str(m) for m in get_messages(respuesta.wsgi_request)]
        self.assertTrue(any("fin de semana" in t for t in textos))

    def test_un_feriado_bloquea_la_planilla(self):
        DiaNoLaborable.objects.create(fecha=MARTES, descripcion="Feriado de prueba")
        self.assertContains(self.ver(MARTES), "es feriado")

    def test_una_fecha_futura_bloquea_la_planilla(self):
        manana = timezone.localdate() + timedelta(days=1)
        self.assertContains(self.ver(manana), "fecha futura")

    def test_un_periodo_cerrado_bloquea_la_planilla(self):
        cerrar_mes(usuario=self.usuario, token=self.token, anio=2026, mes=9)
        self.assertContains(self.ver(), "El período está cerrado")

    def test_una_fecha_invalida_redirige(self):
        respuesta = self.client.get(self.url, {"fecha": "abc"})
        self.assertRedirects(respuesta, self.url)

    def test_sin_permiso_responde_403(self):
        self.client.force_login(crear_usuario("sinrol"))
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url).status_code, 403)

    def test_quien_carga_puede_usarla(self):
        self.client.force_login(crear_usuario("bedel", PERMISOS_CARGA))
        self.assertEqual(self.ver().status_code, 200)

    def test_en_una_jornada_cerrada_con_autorizacion_debe_indicar_el_motivo(self):
        cerrar_dia(usuario=self.usuario, token=self.token, fecha=LUNES)
        respuesta = self.ver()
        self.assertContains(respuesta, "Motivo de la carga en una jornada cerrada")

        self.enviar({f"marca-{self.gomez.pk}": self.marca_p.pk})
        self.assertFalse(RegistroAsistencia.objects.exists())

        self.enviar(
            {
                f"marca-{self.gomez.pk}": self.marca_p.pk,
                "motivo": "Carga omitida por corte de energía",
            }
        )
        self.assertEqual(RegistroAsistencia.objects.count(), 1)

    def test_en_una_jornada_cerrada_quien_solo_carga_ve_la_planilla_bloqueada(self):
        cerrar_dia(usuario=self.usuario, token=self.token, fecha=LUNES)
        self.client.force_login(crear_usuario("bedel", PERMISOS_CARGA))
        respuesta = self.ver()
        self.assertContains(respuesta, "requiere autorización de Secretaría")
        self.assertNotContains(respuesta, "Guardar planilla")

    def test_el_registro_diario_enlaza_a_la_planilla(self):
        respuesta = self.client.get(
            reverse("asistencia:registro_diario"), {"fecha": LUNES.isoformat()}
        )
        self.assertContains(
            respuesta, f"{self.url}?fecha={LUNES.isoformat()}"
        )


class CierreMensualTests(BaseAsistenciaTests):
    def test_no_cierra_con_registros_sin_validar(self):
        self.guardar()
        with self.assertRaises(ValidationError):
            cerrar_mes(
                usuario=self.usuario, token=self.token, anio=2026, mes=9
            )

    def test_cierra_con_todo_validado_y_registra_el_evento(self):
        registro = self.guardar()
        validar_asistencia(
            usuario=self.usuario, token=self.token, registro_id=registro.pk
        )
        cierre = cerrar_mes(
            usuario=self.usuario, token=self.token, anio=2026, mes=9
        )
        self.assertEqual(cierre.estado, CierreMensual.Estado.CERRADO)
        self.assertEqual(cierre.cerrado_por, self.usuario)
        self.assertTrue(
            EventoAsistencia.objects.filter(
                cierre=cierre, accion=EventoAsistencia.Accion.CERRAR
            ).exists()
        )

    def test_no_cierra_dos_veces_el_mismo_periodo(self):
        cerrar_mes(usuario=self.usuario, token=self.token, anio=2026, mes=9)
        with self.assertRaises(ValidationError):
            cerrar_mes(
                usuario=self.usuario, token=self.token, anio=2026, mes=9
            )

    def test_mes_fuera_de_rango(self):
        with self.assertRaises(ValidationError):
            cerrar_mes(
                usuario=self.usuario, token=self.token, anio=2026, mes=13
            )

    def test_periodo_cerrado_impide_guardar(self):
        cerrar_mes(usuario=self.usuario, token=self.token, anio=2026, mes=9)
        with self.assertRaises(ValidationError):
            self.guardar()

    def test_reabrir_sin_permiso(self):
        cerrar_mes(usuario=self.usuario, token=self.token, anio=2026, mes=9)
        with self.assertRaises(PermissionDenied):
            reabrir_mes(
                usuario=self.usuario,
                token=self.token,
                anio=2026,
                mes=9,
                motivo="Corrección de una carga errónea",
            )

    def test_reabrir_con_permiso_exige_motivo_y_permite_guardar(self):
        superusuario = User.objects.create_superuser("jefa")
        token = str(uuid.uuid4())
        adquirir_sesion_edicion(superusuario, token)
        cerrar_mes(usuario=self.usuario, token=self.token, anio=2026, mes=9)

        with self.assertRaises(ValidationError):
            reabrir_mes(
                usuario=superusuario, token=token, anio=2026, mes=9, motivo="corto"
            )

        cierre = reabrir_mes(
            usuario=superusuario,
            token=token,
            anio=2026,
            mes=9,
            motivo="Corrección de una carga errónea",
        )
        self.assertEqual(cierre.estado, CierreMensual.Estado.ABIERTO)
        self.assertTrue(
            EventoAsistencia.objects.filter(
                cierre=cierre, accion=EventoAsistencia.Accion.REABRIR
            ).exists()
        )
        self.guardar()


class ConcurrenciaTests(TestCase):
    def setUp(self):
        self.usuarios = [
            User.objects.create_user(f"op{i}") for i in range(3)
        ]

    def test_el_limite_de_operadores_es_dos(self):
        self.assertEqual(MAX_OPERADORES, 2)

    def test_un_tercer_operador_es_rechazado(self):
        adquirir_sesion_edicion(self.usuarios[0], str(uuid.uuid4()))
        adquirir_sesion_edicion(self.usuarios[1], str(uuid.uuid4()))
        with self.assertRaises(ValidationError):
            adquirir_sesion_edicion(self.usuarios[2], str(uuid.uuid4()))

    def test_la_misma_sesion_no_ocupa_otro_lugar(self):
        token = str(uuid.uuid4())
        adquirir_sesion_edicion(self.usuarios[0], token)
        adquirir_sesion_edicion(self.usuarios[0], token)
        adquirir_sesion_edicion(self.usuarios[1], str(uuid.uuid4()))
        self.assertEqual(SesionEdicion.objects.filter(activa=True).count(), 2)

    def test_una_sesion_expirada_libera_el_lugar(self):
        adquirir_sesion_edicion(self.usuarios[0], str(uuid.uuid4()))
        adquirir_sesion_edicion(self.usuarios[1], str(uuid.uuid4()))
        SesionEdicion.objects.filter(usuario=self.usuarios[0]).update(
            expira_en=timezone.now() - timedelta(minutes=1)
        )
        adquirir_sesion_edicion(self.usuarios[2], str(uuid.uuid4()))

    def test_liberar_la_sesion_libera_el_lugar(self):
        token = str(uuid.uuid4())
        adquirir_sesion_edicion(self.usuarios[0], token)
        adquirir_sesion_edicion(self.usuarios[1], str(uuid.uuid4()))
        liberar_sesion_edicion(self.usuarios[0], token)
        adquirir_sesion_edicion(self.usuarios[2], str(uuid.uuid4()))

    def test_el_token_de_otro_usuario_se_deniega(self):
        token = str(uuid.uuid4())
        adquirir_sesion_edicion(self.usuarios[0], token)
        with self.assertRaises(PermissionDenied):
            adquirir_sesion_edicion(self.usuarios[1], token)

    def test_una_sesion_vencida_se_reactiva_con_el_mismo_token(self):
        token = str(uuid.uuid4())
        sesion = adquirir_sesion_edicion(self.usuarios[0], token)
        SesionEdicion.objects.filter(pk=sesion.pk).update(
            expira_en=timezone.now() - timedelta(minutes=1)
        )
        reactivada = adquirir_sesion_edicion(self.usuarios[0], token)
        self.assertEqual(reactivada.pk, sesion.pk)
        self.assertTrue(reactivada.activa)
        self.assertGreater(
            reactivada.expira_en, timezone.now() + timedelta(minutes=10)
        )
        self.assertEqual(SesionEdicion.objects.filter(token=token).count(), 1)

    def test_una_sesion_liberada_se_reactiva_con_el_mismo_token(self):
        token = str(uuid.uuid4())
        adquirir_sesion_edicion(self.usuarios[0], token)
        liberar_sesion_edicion(self.usuarios[0], token)
        reactivada = adquirir_sesion_edicion(self.usuarios[0], token)
        self.assertTrue(reactivada.activa)
        self.assertEqual(SesionEdicion.objects.filter(token=token).count(), 1)

    def test_reactivar_una_sesion_vencida_respeta_el_maximo_de_operadores(self):
        token = str(uuid.uuid4())
        sesion = adquirir_sesion_edicion(self.usuarios[0], token)
        SesionEdicion.objects.filter(pk=sesion.pk).update(
            expira_en=timezone.now() - timedelta(minutes=1)
        )
        # Otros dos operadores toman los dos lugares mientras está vencida.
        adquirir_sesion_edicion(self.usuarios[1], str(uuid.uuid4()))
        adquirir_sesion_edicion(self.usuarios[2], str(uuid.uuid4()))
        with self.assertRaises(ValidationError):
            adquirir_sesion_edicion(self.usuarios[0], token)
        self.assertFalse(SesionEdicion.objects.get(token=token).activa)

    def test_el_token_vencido_de_otro_usuario_se_deniega(self):
        token = str(uuid.uuid4())
        sesion = adquirir_sesion_edicion(self.usuarios[0], token)
        SesionEdicion.objects.filter(pk=sesion.pk).update(
            expira_en=timezone.now() - timedelta(minutes=1)
        )
        with self.assertRaises(PermissionDenied):
            adquirir_sesion_edicion(self.usuarios[1], token)

    def test_renovar_una_sesion_expirada(self):
        token = str(uuid.uuid4())
        adquirir_sesion_edicion(self.usuarios[0], token)
        SesionEdicion.objects.update(
            expira_en=timezone.now() - timedelta(minutes=1)
        )
        with self.assertRaises(ValidationError):
            renovar_sesion_edicion(self.usuarios[0], token)

    def test_renovar_extiende_la_expiracion(self):
        token = str(uuid.uuid4())
        sesion = adquirir_sesion_edicion(self.usuarios[0], token)
        SesionEdicion.objects.update(
            expira_en=timezone.now() + timedelta(minutes=1)
        )
        renovada = renovar_sesion_edicion(self.usuarios[0], token)
        self.assertGreater(
            renovada.expira_en, timezone.now() + timedelta(minutes=10)
        )
        self.assertEqual(renovada.pk, sesion.pk)


class VistasTests(BaseAsistenciaTests):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.usuario)

    def test_registro_diario_con_fecha_invalida_redirige(self):
        respuesta = self.client.get(
            reverse("asistencia:registro_diario"), {"fecha": "abc"}
        )
        self.assertRedirects(respuesta, reverse("asistencia:registro_diario"))

    def test_registro_diario_con_fecha_valida(self):
        respuesta = self.client.get(
            reverse("asistencia:registro_diario"), {"fecha": LUNES.isoformat()}
        )
        self.assertEqual(respuesta.status_code, 200)

    def test_el_formulario_de_carga_se_muestra(self):
        respuesta = self.client.get(reverse("asistencia:crear_asistencia"))
        self.assertEqual(respuesta.status_code, 200)

    def test_el_error_de_servicio_se_muestra_sin_formato_de_lista(self):
        cerrar_mes(usuario=self.usuario, token=self.token, anio=2026, mes=9)
        respuesta = self.client.post(
            reverse("asistencia:crear_asistencia"),
            {
                "designacion": self.designacion.pk,
                "fecha": LUNES.isoformat(),
                "marca": self.marca_p.pk,
                "horas_inasistidas": "0",
                "observaciones": "",
            },
        )
        textos = [str(m) for m in get_messages(respuesta.wsgi_request)]
        self.assertTrue(any("El período está cerrado" in t for t in textos))
        self.assertFalse(any(t.startswith("[") for t in textos))

    def test_guardar_con_la_sesion_vencida_no_da_error_500(self):
        # A3: pasados 15 minutos sin guardar, el token de la sesión de Django
        # sigue vigente pero la sesión de edición ya venció.
        sesion = self.client.session
        sesion["asistencia_token"] = self.token
        sesion.save()
        SesionEdicion.objects.filter(token=self.token).update(
            expira_en=timezone.now() - timedelta(minutes=1)
        )

        respuesta = self.client.post(
            reverse("asistencia:crear_asistencia"),
            {
                "designacion": self.designacion.pk,
                "fecha": LUNES.isoformat(),
                "marca": self.marca_p.pk,
                "horas_inasistidas": "0",
                "observaciones": "",
            },
        )

        self.assertRedirects(
            respuesta,
            f"{reverse('asistencia:registro_diario')}"
            f"?fecha={LUNES.isoformat()}",
        )
        self.assertTrue(
            RegistroAsistencia.objects.filter(
                designacion=self.designacion, fecha=LUNES
            ).exists()
        )
        self.assertEqual(
            SesionEdicion.objects.filter(token=self.token).count(), 1
        )

    def test_la_paginacion_del_historial_conserva_los_filtros(self):
        for dia in range(30):
            RegistroAsistencia.objects.create(
                designacion=self.designacion,
                fecha=date(2026, 3, 1) + timedelta(days=dia),
                marca=self.marca_p,
            )
        respuesta = self.client.get(
            reverse("asistencia:historial"), {"dni": "30123456"}
        )
        self.assertContains(respuesta, "?dni=30123456&page=2")

    def test_el_admin_no_permite_crear_ni_borrar_marcas(self):
        from django.contrib import admin
        from django.test import RequestFactory

        peticion = RequestFactory().get("/")
        peticion.user = User.objects.create_superuser("root")
        modelo_admin = admin.site._registry[MarcaAsistencia]
        self.assertFalse(modelo_admin.has_add_permission(peticion))
        self.assertFalse(modelo_admin.has_delete_permission(peticion))
