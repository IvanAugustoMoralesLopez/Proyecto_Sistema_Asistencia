from datetime import date, timedelta

from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory, TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from asistencias.models import EventoAsistencia
from reportes.auditoria import AccionesReportes

from .models import (
    Persona,
    Cargo,
    Designacion,
    HistorialDesignacion,
    Horario,
    ImportacionPersonalError,
)
from .forms import DesignacionForm, NuevaDesignacionForm, PersonaForm
from .views import _procesar_csv, gestion_legajos


class DesignacionTests(TestCase):
    def otorgar_permiso(self, usuario, codename):
        usuario.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="personal",
                codename=codename,
            )
        )

    def setUp(self):
        self.persona = Persona.objects.create(
            dni="30123456",
            apellido_nombre="Docente de prueba",
        )
        self.cargo = Cargo.objects.create(
            codigo="PROF",
            descripcion="Profesor",
        )

    def test_crear_designacion(self):
        designacion = Designacion.objects.create(
            persona=self.persona,
            cargo=self.cargo,
            desde=date(2026, 3, 1),
        )
        self.assertEqual(
            designacion.persona.apellido_nombre,
            "Docente de prueba",
        )

    def test_fecha_final_no_puede_ser_anterior(self):
        designacion = Designacion(
            persona=self.persona,
            cargo=self.cargo,
            desde=date(2026, 3, 10),
            hasta=date(2026, 3, 1),
        )
        with self.assertRaises(ValidationError):
            designacion.full_clean()

    def test_historial_registra_alta_cambio_y_baja(self):
        designacion = Designacion.objects.create(
            persona=self.persona,
            cargo=self.cargo,
            situacion_revista=Designacion.Situacion.INTERINO,
            desde=date(2026, 3, 1),
        )
        designacion.situacion_revista = Designacion.Situacion.TITULAR
        designacion.save()
        designacion.activo = False
        designacion.save()

        acciones = list(
            designacion.historial.order_by("pk").values_list("accion", flat=True)
        )
        self.assertEqual(
            acciones,
            [
                HistorialDesignacion.Accion.ALTA,
                HistorialDesignacion.Accion.CAMBIO_SITUACION,
                HistorialDesignacion.Accion.BAJA,
            ],
        )
        self.assertEqual(
            designacion.historial.all()[1].datos_anteriores["situacion_revista"],
            Designacion.Situacion.INTERINO,
        )

    def test_historial_audita_cambios_de_vinculo_de_suplencia(self):
        titular = Persona.objects.create(
            dni="30123463",
            apellido_nombre="Titular",
        )
        reemplazo_inicial = Designacion.objects.create(
            persona=titular,
            cargo=self.cargo,
            desde=date(2026, 3, 1),
            hasta=date(2026, 12, 31),
        )
        reemplazo_nuevo = Designacion.objects.create(
            persona=titular,
            cargo=self.cargo,
            desde=date(2026, 4, 1),
            hasta=date(2026, 12, 31),
        )
        suplencia = Designacion.objects.create(
            persona=self.persona,
            cargo=self.cargo,
            desde=date(2026, 5, 1),
            hasta=date(2026, 5, 31),
            es_suplencia=True,
            reemplaza=reemplazo_inicial,
        )

        suplencia.reemplaza = reemplazo_nuevo
        suplencia.plazo_indeterminado = True
        suplencia.hasta = None
        suplencia.save()

        evento = suplencia.historial.latest("pk")
        self.assertEqual(evento.accion, HistorialDesignacion.Accion.MODIFICACION)
        self.assertEqual(
            evento.datos_anteriores["reemplaza_id"],
            reemplazo_inicial.pk,
        )
        self.assertEqual(evento.datos_nuevos["reemplaza_id"], reemplazo_nuevo.pk)
        self.assertFalse(evento.datos_anteriores["plazo_indeterminado"])
        self.assertTrue(evento.datos_nuevos["plazo_indeterminado"])

    def test_vigencia_de_designacion_respeta_rango_de_fechas(self):
        designacion = Designacion.objects.create(
            persona=self.persona,
            cargo=self.cargo,
            desde=date(2026, 3, 1),
            hasta=date(2026, 11, 30),
        )

        self.assertFalse(designacion.vigente_en(date(2026, 2, 28)))
        self.assertTrue(designacion.vigente_en(date(2026, 7, 1)))
        self.assertFalse(designacion.vigente_en(date(2026, 12, 1)))

    def test_suplencia_requiere_fecha_de_cese_o_plazo_indeterminado(self):
        designacion = Designacion(
            persona=self.persona,
            cargo=self.cargo,
            desde=date(2026, 3, 1),
            es_suplencia=True,
        )

        with self.assertRaises(ValidationError):
            designacion.full_clean()

    def test_mismo_suplente_puede_tener_designaciones_en_periodos_distintos(self):
        primeras_fechas = {
            "desde": date(2026, 3, 1),
            "hasta": date(2026, 6, 30),
        }
        segunda_fechas = {
            "desde": date(2026, 7, 1),
            "hasta": date(2026, 11, 30),
        }

        for fechas in (primeras_fechas, segunda_fechas):
            designacion = Designacion(
                persona=self.persona,
                cargo=self.cargo,
                situacion_revista=Designacion.Situacion.SUPLENTE,
                es_suplencia=True,
                **fechas,
            )
            designacion.full_clean()
            designacion.save()

        self.assertEqual(
            Designacion.objects.filter(persona=self.persona, es_suplencia=True).count(),
            2,
        )

    def test_asistente_vincula_suplencia_con_designacion_vigente(self):
        titular = Persona.objects.create(
            dni="30123461",
            apellido_nombre="Docente titular",
        )
        designacion_titular = Designacion.objects.create(
            persona=titular,
            cargo=self.cargo,
            desde=date(2026, 3, 1),
            hasta=date(2026, 12, 31),
        )
        form = NuevaDesignacionForm(
            data={
                "persona": self.persona.pk,
                "cargo": self.cargo.pk,
                "situacion_revista": Designacion.Situacion.SUPLENTE,
                "desde": "2026-07-01",
                "hasta": "2026-07-31",
                "es_suplencia": "on",
                "reemplaza": designacion_titular.pk,
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        suplencia = form.save()
        self.assertEqual(suplencia.reemplaza, designacion_titular)

    def test_comando_da_baja_designaciones_vencidas_y_registra_historial(self):
        hoy = timezone.localdate()
        designacion = Designacion.objects.create(
            persona=self.persona,
            cargo=self.cargo,
            desde=hoy - timedelta(days=10),
            hasta=hoy - timedelta(days=1),
        )

        call_command("cerrar_designaciones_vencidas", verbosity=0)

        designacion.refresh_from_db()
        self.assertFalse(designacion.activo)
        self.assertEqual(
            designacion.historial.latest("pk").accion,
            HistorialDesignacion.Accion.BAJA,
        )

    def test_csv_importa_suplencia_con_plazo_indeterminado(self):
        contenido = (
            "dni,apellido_nombre,cargo_codigo,desde,es_suplencia,"
            "plazo_indeterminado\n"
            "30999888,Suplente CSV,PROF,2026-03-01,true,true\n"
        ).encode("utf-8")
        archivo = SimpleUploadedFile("suplencias.csv", contenido, content_type="text/csv")

        total, rechazadas = _procesar_csv(archivo)

        designacion = Designacion.objects.get(persona_id="30999888")
        self.assertEqual(total, 1)
        self.assertEqual(rechazadas, 0)
        self.assertTrue(designacion.es_suplencia)
        self.assertTrue(designacion.plazo_indeterminado)
        self.assertIsNone(designacion.hasta)

    def test_csv_importa_suplencia_vinculada_a_designacion_vigente(self):
        titular = Persona.objects.create(
            dni="30123462",
            apellido_nombre="Titular de prueba",
        )
        designacion_titular = Designacion.objects.create(
            persona=titular,
            cargo=self.cargo,
            desde=date(2026, 3, 1),
            hasta=date(2026, 12, 31),
        )
        archivo = SimpleUploadedFile(
            "suplencias.csv",
            (
                "dni,apellido_nombre,cargo_codigo,situacion_revista,desde,hasta,"
                "es_suplencia,reemplaza_id\n"
                f"30123456,Docente de prueba,PROF,SUP,2026-07-01,2026-07-31,"
                f"true,{designacion_titular.pk}\n"
            ).encode("utf-8"),
        )

        total, rechazadas = _procesar_csv(archivo)

        suplencia = Designacion.objects.get(
            persona=self.persona,
            es_suplencia=True,
        )
        self.assertEqual((total, rechazadas), (1, 0))
        self.assertEqual(suplencia.reemplaza, designacion_titular)

    def test_formulario_mantiene_el_dni_inmutable_al_editar(self):
        form = PersonaForm(
            data={
                "apellido": "Apellido actualizado",
                "nombres": "Docente",
                "sexo": "F",
                "activa": "on",
            },
            instance=self.persona,
        )

        self.assertIn("apellido", form.fields)
        self.assertIn("nombres", form.fields)
        self.assertTrue(form.is_valid(), form.errors)
        persona = form.save()
        self.assertEqual(persona.pk, "30123456")
        self.assertEqual(persona.apellido_nombre, "Apellido actualizado, Docente")
        self.assertEqual(persona.apellido, "Apellido actualizado")
        self.assertEqual(persona.nombres, "Docente")

    def test_formulario_guarda_horas_semanales_por_dia(self):
        form = DesignacionForm(
            data={
                "cargo": self.cargo.pk,
                "espacio_curricular": "",
                "unidad_educativa": "",
                "situacion_revista": Designacion.Situacion.SUPLENTE,
                "anio_curso": "",
                "division_seccion": "",
                "turno": "Mañana",
                "hs_catedra": "4",
                "jornada": "",
                "especialidad": "",
                "disp_alta_nro": "",
                "sello_regional_as": "",
                "motivo": "",
                "norma_tipo": "",
                "norma_numero": "",
                "norma_anio": "",
                "organismo_emisor": "",
                "desde": "2026-03-01",
                "hasta": "",
                "pof": "",
                "anio_pof": "",
                "novedad": "",
                "observaciones": "",
                "horas_lun": "3",
                "horas_mar": "0",
                "horas_mie": "2",
                "horas_jue": "0",
                "horas_vie": "0",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.instance.persona = self.persona
        designacion = form.save()

        horas = dict(
            Horario.objects.filter(designacion=designacion).values_list(
                "dia", "horas_catedra"
            )
        )
        self.assertEqual(horas, {"LUN": 3, "MIE": 2})

    def test_csv_continua_importacion_y_registra_fila_rechazada(self):
        archivo = SimpleUploadedFile(
            "personal.csv",
            (
                "DNI,apellido_nombre,cargo_codigo,desde\n"
                "30123457,Docente válido,PROF,2026-03-01\n"
                "99999999,,PROF,2026-03-01\n"
            ).encode("utf-8"),
        )

        total, rechazadas = _procesar_csv(archivo)

        self.assertEqual(total, 2)
        self.assertEqual(rechazadas, 1)
        self.assertTrue(Persona.objects.filter(pk="30123457").exists())
        self.assertEqual(
            Designacion.objects.filter(persona_id="30123457").count(),
            1,
        )
        self.assertEqual(
            ImportacionPersonalError.objects.get().numero_fila,
            3,
        )

    def test_csv_rechaza_designacion_duplicada(self):
        contenido = (
            "dni,apellido_nombre,cargo_codigo,desde\n"
            "30123456,Docente de prueba,PROF,2026-03-01\n"
            "30123456,Docente de prueba,PROF,2026-03-01\n"
        ).encode("utf-8")
        archivo = SimpleUploadedFile("designaciones.csv", contenido)

        total, rechazadas = _procesar_csv(archivo)

        self.assertEqual(total, 2)
        self.assertEqual(rechazadas, 1)
        self.assertEqual(Designacion.objects.filter(persona=self.persona).count(), 1)

    def test_importacion_csv_registra_auditoria(self):
        usuario = get_user_model().objects.create_user(
            username="csv-audit-test",
            password="test-password",
        )
        self.otorgar_permiso(usuario, "change_persona")
        self.otorgar_permiso(usuario, "add_persona")
        self.otorgar_permiso(usuario, "add_designacion")
        cliente = Client()
        cliente.force_login(usuario)
        archivo = SimpleUploadedFile(
            "personal.csv",
            (
                "dni,apellido_nombre,cargo_codigo,desde\n"
                "30123457,Docente auditado,PROF,2026-03-01\n"
            ).encode("utf-8"),
        )

        respuesta = cliente.post(
            reverse("personal:gestion_legajos"),
            {"accion": "importar_csv", "archivo": archivo},
            follow=True,
        )

        self.assertEqual(respuesta.status_code, 200)
        evento = EventoAsistencia.objects.get(
            usuario=usuario,
            accion=AccionesReportes.IMPORTACION,
        )
        self.assertEqual(evento.motivo, "Archivo personal.csv")
        self.assertEqual(evento.despues["filas"], 1)
        self.assertEqual(evento.despues["importadas"], 1)
        self.assertEqual(evento.despues["rechazadas"], 0)

    def test_importacion_csv_funciona_con_permiso_de_alta_sin_change_persona(self):
        usuario = get_user_model().objects.create_user(
            username="csv-add-only-test",
            password="test-password",
        )
        self.otorgar_permiso(usuario, "add_persona")
        cliente = Client()
        cliente.force_login(usuario)
        archivo = SimpleUploadedFile(
            "personal-nuevo.csv",
            b"dni,apellido_nombre\n30123459,Alta CSV\n",
        )

        respuesta = cliente.post(
            reverse("personal:gestion_legajos"),
            {"accion": "importar_csv", "archivo": archivo},
            follow=True,
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(Persona.objects.filter(pk="30123459").exists())
        self.assertContains(respuesta, "1 filas importadas")

    def test_importacion_csv_exige_alta_de_designacion_y_no_change(self):
        usuario = get_user_model().objects.create_user(
            username="csv-designacion-permission-test",
            password="test-password",
        )
        self.otorgar_permiso(usuario, "change_persona")
        self.otorgar_permiso(usuario, "change_designacion")
        cliente = Client()
        cliente.force_login(usuario)
        archivo = SimpleUploadedFile(
            "designacion.csv",
            b"dni,cargo_codigo,desde\n30123456,PROF,2026-03-01\n",
        )

        respuesta = cliente.post(
            reverse("personal:gestion_legajos"),
            {"accion": "importar_csv", "archivo": archivo},
            follow=True,
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Designacion.objects.filter(persona=self.persona).exists())
        self.assertEqual(ImportacionPersonalError.objects.get().numero_fila, 2)

    def test_importacion_csv_de_designacion_acepta_solo_add_designacion(self):
        usuario = get_user_model().objects.create_user(
            username="csv-add-designacion-only-test",
            password="test-password",
        )
        self.otorgar_permiso(usuario, "add_designacion")
        cliente = Client()
        cliente.force_login(usuario)
        archivo = SimpleUploadedFile(
            "designacion.csv",
            b"dni,cargo_codigo,desde\n30123456,PROF,2026-03-01\n",
        )

        respuesta = cliente.post(
            reverse("personal:gestion_legajos"),
            {"accion": "importar_csv", "archivo": archivo},
            follow=True,
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(Designacion.objects.filter(persona=self.persona).exists())
        self.assertEqual(ImportacionPersonalError.objects.count(), 0)

    def test_catalogo_id_inexistente_no_causa_error_500(self):
        usuario = get_user_model().objects.create_user(
            username="catalogo-id-test",
            password="test-password",
        )
        self.otorgar_permiso(usuario, "change_cargo")
        cliente = Client()
        cliente.force_login(usuario)

        respuesta_get = cliente.get(
            reverse("personal:catalogos"),
            {"seccion": "cargos", "editar": "INEXISTENTE"},
        )
        respuesta_post = cliente.post(
            reverse("personal:catalogos"),
            {
                "seccion": "cargos",
                "accion": "eliminar",
                "objeto_id": "INEXISTENTE",
            },
        )

        self.assertNotEqual(respuesta_get.status_code, 500)
        self.assertNotEqual(respuesta_post.status_code, 500)
        self.assertRedirects(
            respuesta_post,
            f"{reverse('personal:catalogos')}?seccion=cargos",
        )

    def test_persona_rechaza_dni_invalido_sin_error_500(self):
        usuario = get_user_model().objects.create_user(
            username="dni-validation-test",
            password="test-password",
        )
        self.otorgar_permiso(usuario, "change_persona")
        self.otorgar_permiso(usuario, "add_persona")
        cliente = Client()
        cliente.force_login(usuario)

        respuesta = cliente.post(
            reverse("personal:gestion_legajos"),
            {
                "accion": "guardar_persona",
                "dni": "ABC123",
                "apellido_nombre": "Docente inválido",
            },
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "DNI")

    def test_id_diseno_invalido_no_causa_error_500(self):
        usuario = get_user_model().objects.create_user(
            username="invalid-designacion-id-test",
            password="test-password",
        )
        self.otorgar_permiso(usuario, "change_persona")
        cliente = Client()
        cliente.force_login(usuario)

        respuesta = cliente.get(
            reverse("personal:gestion_legajos"),
            {
                "dni": self.persona.pk,
                "designacion": "abc",
            },
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "La designación indicada no existe.")

    def test_catalogo_numerico_invalido_no_causa_error_500(self):
        usuario = get_user_model().objects.create_user(
            username="invalid-catalog-id-test",
            password="test-password",
        )
        self.otorgar_permiso(usuario, "change_carrera")
        cliente = Client()
        cliente.force_login(usuario)

        respuesta = cliente.get(
            reverse("personal:catalogos"),
            {"seccion": "carreras", "editar": "abc"},
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertNotIn("500", respuesta.headers.get("Location", ""))

    def test_nombre_persona_sincroniza_campos_compatibles(self):
        persona = Persona.objects.create(
            dni="30123458",
            apellido_nombre="López, Ana María",
            apellido="Viejo",
            nombres="Nombre viejo",
        )

        persona.refresh_from_db()
        self.assertEqual(persona.apellido, "López")
        self.assertEqual(persona.nombres, "Ana María")

    def test_pantalla_renderiza_para_usuario_autenticado(self):
        usuario = get_user_model().objects.create_user(
            username="personal-test",
            password="test-password",
        )
        request = RequestFactory().get("/personal/legajos/")
        request.user = usuario
        self.otorgar_permiso(usuario, "change_persona")

        response = gestion_legajos(request)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Personal docente",
            html=False,
        )

    def test_pantalla_rechaza_usuario_sin_permisos_de_personal(self):
        usuario = get_user_model().objects.create_user(
            username="personal-no-permission-test",
            password="test-password",
        )
        cliente = Client()
        cliente.force_login(usuario)

        respuesta = cliente.get(reverse("personal:gestion_legajos"))

        self.assertEqual(respuesta.status_code, 403)

    def test_ruta_publica_pantalla_redirige_y_usuario_autenticado_la_ve(self):
        cliente = Client()
        url = reverse("personal:gestion_legajos")

        respuesta_anonima = cliente.get(url)
        self.assertEqual(respuesta_anonima.status_code, 302)
        self.assertIn("/accounts/login/", respuesta_anonima.url)

        usuario = get_user_model().objects.create_user(
            username="personal-route-test",
            password="test-password",
        )
        cliente.force_login(usuario)
        self.otorgar_permiso(usuario, "change_persona")
        respuesta_autenticada = cliente.get(url)

        self.assertEqual(respuesta_autenticada.status_code, 200)
        self.assertContains(
            respuesta_autenticada,
            "Personal docente",
        )

    def test_alta_de_legajo_no_requiere_permiso_de_cambio(self):
        usuario = get_user_model().objects.create_user(
            username="personal-add-only-test",
            password="test-password",
        )
        self.otorgar_permiso(usuario, "add_persona")
        cliente = Client()
        cliente.force_login(usuario)

        respuesta_get = cliente.get(reverse("personal:gestion_legajos"))
        respuesta_post = cliente.post(
            reverse("personal:gestion_legajos"),
            {
                "accion": "guardar_persona",
                "dni": "30123460",
                "apellido": "Nuevo",
                "nombres": "Agente",
                "apellido_nombre": "Nuevo, Agente",
            },
        )

        self.assertEqual(respuesta_get.status_code, 200)
        self.assertRedirects(
            respuesta_post,
            f"{reverse('personal:gestion_legajos')}?dni=30123460",
        )
        self.assertTrue(Persona.objects.filter(pk="30123460").exists())

        respuesta_edicion_no_autorizada = cliente.post(
            reverse("personal:gestion_legajos"),
            {
                "accion": "guardar_persona",
                "dni": "30123460",
                "apellido": "Editado",
                "nombres": "Agente",
                "apellido_nombre": "Editado, Agente",
            },
        )
        self.assertEqual(respuesta_edicion_no_autorizada.status_code, 403)

    def test_planilla_muestra_designacion_guardada_y_links_de_creacion(self):
        Designacion.objects.create(
            persona=self.persona,
            cargo=self.cargo,
            situacion_revista=Designacion.Situacion.TITULAR,
            desde=date(2026, 3, 1),
        )
        usuario = get_user_model().objects.create_user(
            username="designaciones-list-test",
            password="test-password",
        )
        self.otorgar_permiso(usuario, "change_designacion")
        cliente = Client()
        cliente.force_login(usuario)

        respuesta = cliente.get(reverse("pantalla_personal"), follow=True)

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "30123456")
        self.assertContains(respuesta, "Profesor")
        self.assertContains(respuesta, "/personal/legajos/")
        self.assertContains(respuesta, "/personal/designaciones/nueva/")

    def test_crear_designacion_desde_formulario_y_volver_a_planilla(self):
        usuario = get_user_model().objects.create_user(
            username="designaciones-create-test",
            password="test-password",
        )
        cliente = Client()
        cliente.force_login(usuario)
        self.otorgar_permiso(usuario, "add_designacion")
        self.otorgar_permiso(usuario, "change_designacion")

        respuesta = cliente.post(
            reverse("personal:nueva_designacion"),
            data={
                "persona": self.persona.pk,
                "cargo": self.cargo.pk,
                "espacio_curricular": "",
                "unidad_educativa": "",
                "situacion_revista": Designacion.Situacion.INTERINO,
                "anio_curso": "",
                "division_seccion": "",
                "turno": "",
                "hs_catedra": "",
                "jornada": "",
                "especialidad": "",
                "disp_alta_nro": "",
                "sello_regional_as": "",
                "motivo": "",
                "norma_tipo": "",
                "norma_numero": "",
                "norma_anio": "",
                "organismo_emisor": "",
                "desde": "2026-03-01",
                "hasta": "",
                "pof": "",
                "anio_pof": "",
                "novedad": "",
                "observaciones": "",
                "horas_lun": "2",
                "horas_mar": "0",
                "horas_mie": "0",
                "horas_jue": "0",
                "horas_vie": "0",
            },
            follow=True,
        )

        self.assertRedirects(respuesta, reverse("inicio_personal"))
        self.assertContains(respuesta, "30123456")
        self.assertContains(respuesta, "Profesor")
        designacion = Designacion.objects.get(
            persona=self.persona,
            cargo=self.cargo,
        )
        self.assertEqual(
            designacion.horarios.get(dia=Horario.Dia.LUNES).horas_catedra,
            2,
        )

    def test_alta_de_designacion_no_requiere_permiso_de_cambio(self):
        usuario = get_user_model().objects.create_user(
            username="designaciones-add-only-test",
            password="test-password",
        )
        self.otorgar_permiso(usuario, "add_designacion")
        cliente = Client()
        cliente.force_login(usuario)

        respuesta = cliente.post(
            reverse("personal:nueva_designacion"),
            {
                "persona": self.persona.pk,
                "cargo": self.cargo.pk,
                "situacion_revista": Designacion.Situacion.INTERINO,
                "desde": "2026-03-01",
                "horas_lun": "0",
                "horas_mar": "0",
                "horas_mie": "0",
                "horas_jue": "0",
                "horas_vie": "0",
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(respuesta.headers["Location"], reverse("inicio_personal"))
        self.assertTrue(
            Designacion.objects.filter(persona=self.persona, cargo=self.cargo).exists()
        )

    def test_error_de_formulario_de_designacion_se_muestra_sin_error_500(self):
        usuario = get_user_model().objects.create_user(
            username="personal-designacion-invalid-form-test",
            password="test-password",
        )
        self.otorgar_permiso(usuario, "add_designacion")
        cliente = Client()
        cliente.force_login(usuario)

        respuesta = cliente.post(
            reverse("personal:gestion_legajos"),
            {
                "accion": "guardar_designacion",
                "dni": self.persona.pk,
                "cargo": self.cargo.pk,
                "espacio_curricular": "",
                "unidad_educativa": "",
                "situacion_revista": Designacion.Situacion.INTERINO,
                "desde": "2026-03-10",
                "hasta": "2026-03-01",
                "plazo_indeterminado": "",
            },
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(
            respuesta,
            "La fecha de finalización no puede ser anterior al inicio.",
        )
        self.assertFalse(Designacion.objects.filter(persona=self.persona).exists())

    def test_editar_designacion_abre_y_guarda_sobre_el_registro(self):
        designacion = Designacion.objects.create(
            persona=self.persona,
            cargo=self.cargo,
            situacion_revista=Designacion.Situacion.TITULAR,
            desde=date(2026, 3, 1),
        )
        usuario = get_user_model().objects.create_user(
            username="designaciones-edit-test",
            password="test-password",
        )
        cliente = Client()
        cliente.force_login(usuario)
        self.otorgar_permiso(usuario, "change_designacion")

        respuesta = cliente.get(
            reverse("personal:editar_designacion", args=[designacion.pk])
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Modificar designación docente")
        self.assertContains(respuesta, self.persona.dni)