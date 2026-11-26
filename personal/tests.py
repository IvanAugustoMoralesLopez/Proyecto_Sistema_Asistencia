from datetime import date, timedelta

from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory, TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from asistencias.models import EventoAsistencia
from reportes.auditoria import AccionesReportes

from .models import (
    Persona,
    Cargo,
    Carrera,
    Designacion,
    EspacioCurricular,
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
                "hs_catedra": "2",
                "horas_lun": "2",
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
                "apellido_nombre": "Apellido actualizado, Docente",
                "sexo": "F",
                "activa": "on",
            },
            instance=self.persona,
        )

        self.assertNotIn("apellido", form.fields)
        self.assertNotIn("nombres", form.fields)
        self.assertEqual(form.fields["apellido_nombre"].label, "Nombre y Apellido")
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
                # El horario (3 + 2) tiene que sumar las horas nombradas.
                "hs_catedra": "5",
                "jornada": "",
                "disp_alta_nro": "",
                "sello_regional_as": "",
                "motivo": "",
                "norma_tipo": "",
                "norma_numero": "",
                "norma_anio": "",
                "organismo_emisor": "",
                "desde": "2026-03-01",
                # Suplente sin fecha de cese: plazo indeterminado.
                "hasta": "SIN TERMINO",
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

        # RF-06: primero la vista previa (no guarda nada), después la confirmación.
        previa = cliente.post(
            reverse("personal:gestion_legajos"),
            {"accion": "importar_csv", "archivo": archivo},
        )
        self.assertEqual(previa.status_code, 200)
        self.assertContains(previa, "Todavía no se guardó nada")
        respuesta = cliente.post(
            reverse("personal:gestion_legajos"),
            {"accion": "confirmar_csv"},
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

        # RF-06: primero la vista previa (no guarda nada), después la confirmación.
        previa = cliente.post(
            reverse("personal:gestion_legajos"),
            {"accion": "importar_csv", "archivo": archivo},
        )
        self.assertEqual(previa.status_code, 200)
        self.assertContains(previa, "Todavía no se guardó nada")
        respuesta = cliente.post(
            reverse("personal:gestion_legajos"),
            {"accion": "confirmar_csv"},
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

        # RF-06: primero la vista previa (no guarda nada), después la confirmación.
        previa = cliente.post(
            reverse("personal:gestion_legajos"),
            {"accion": "importar_csv", "archivo": archivo},
        )
        self.assertEqual(previa.status_code, 200)
        self.assertContains(previa, "Todavía no se guardó nada")
        respuesta = cliente.post(
            reverse("personal:gestion_legajos"),
            {"accion": "confirmar_csv"},
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

        # RF-06: primero la vista previa (no guarda nada), después la confirmación.
        previa = cliente.post(
            reverse("personal:gestion_legajos"),
            {"accion": "importar_csv", "archivo": archivo},
        )
        self.assertEqual(previa.status_code, 200)
        self.assertContains(previa, "Todavía no se guardó nada")
        respuesta = cliente.post(
            reverse("personal:gestion_legajos"),
            {"accion": "confirmar_csv"},
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
                "hs_catedra": "2",
                "jornada": "",
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
                "hs_catedra": "2",
                "horas_lun": "2",
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


class RequerimientosV2PersonalTests(TestCase):
    """RF-05, RF-06 y RN-09 según el Documento de Requerimientos v2.0."""

    def setUp(self):
        from .models import TipoInstrumentoLegal

        self.TipoInstrumentoLegal = TipoInstrumentoLegal
        self.cargo = Cargo.objects.create(codigo="PROF", descripcion="Profesor")
        self.persona = Persona.objects.create(
            dni="30123456", apellido_nombre="PEREZ, JUAN"
        )
        self.admin = get_user_model().objects.create_superuser(
            username="admin-v2", password="x"
        )
        self.cliente = Client()
        self.cliente.force_login(self.admin)
        self.url = reverse("personal:gestion_legajos")

    def csv(self, texto, nombre="personal.csv"):
        return SimpleUploadedFile(nombre, texto.encode("utf-8"))

    # ── RF-05: catálogo de tipos de instrumento legal ──

    def test_el_catalogo_trae_resolucion_y_disposicion(self):
        self.assertEqual(
            set(self.TipoInstrumentoLegal.objects.values_list("nombre", flat=True)),
            {"Resolución", "Disposición"},
        )

    def test_abmc_de_tipos_de_instrumento_legal(self):
        url = reverse("personal:catalogos") + "?seccion=instrumentos"

        # Alta
        self.cliente.post(url, {"accion": "guardar", "nombre": "Decreto", "activo": "on"})
        decreto = self.TipoInstrumentoLegal.objects.get(nombre="Decreto")
        # Consulta
        self.assertContains(self.cliente.get(url), "Decreto")
        # Modificación
        self.cliente.post(
            url,
            {"accion": "guardar", "objeto_id": decreto.pk, "nombre": "Decreto provincial", "activo": "on"},
        )
        decreto.refresh_from_db()
        self.assertEqual(decreto.nombre, "Decreto provincial")
        # Baja lógica: no se elimina
        self.cliente.post(url, {"accion": "eliminar", "objeto_id": decreto.pk})
        decreto.refresh_from_db()
        self.assertFalse(decreto.activo)

    def test_un_tipo_nuevo_se_ofrece_en_la_designacion(self):
        from .forms import DesignacionForm

        self.TipoInstrumentoLegal.objects.create(nombre="Decreto")
        opciones = [valor for valor, _ in DesignacionForm().fields["norma_tipo"].choices]
        self.assertIn("Decreto", opciones)

    # ── RN-09: SIN INICIO / SIN TERMINO ──

    def datos_designacion(self, **cambios):
        datos = {
            "persona": self.persona.pk,
            "cargo": self.cargo.pk,
            "situacion_revista": "TIT",
            "norma_tipo": "",
            "desde": "SIN INICIO",
            "hasta": "SIN TERMINO",
            "hs_catedra": "2",
            "horas_lun": "2",
        }
        datos.update(cambios)
        return datos

    def test_el_formulario_acepta_las_cadenas_especiales(self):
        from .forms import NuevaDesignacionForm

        form = NuevaDesignacionForm(self.datos_designacion())
        self.assertTrue(form.is_valid(), form.errors)
        designacion = form.save()

        self.assertTrue(designacion.sin_inicio)
        self.assertIsNone(designacion.hasta)
        self.assertEqual(designacion.desde_texto, "SIN INICIO")
        self.assertEqual(designacion.hasta_texto, "SIN TERMINO")
        # SIN INICIO / SIN TERMINO = vigente en cualquier fecha.
        self.assertTrue(designacion.vigente_en(date(2010, 5, 5)))
        self.assertTrue(designacion.vigente_en(date(2040, 5, 5)))

    def test_el_formulario_acepta_fechas_en_los_dos_formatos(self):
        from .forms import NuevaDesignacionForm

        form = NuevaDesignacionForm(
            self.datos_designacion(desde="01/03/2026", hasta="2026-12-31")
        )
        self.assertTrue(form.is_valid(), form.errors)
        designacion = form.save()
        self.assertEqual(designacion.desde, date(2026, 3, 1))
        self.assertEqual(designacion.hasta, date(2026, 12, 31))
        self.assertFalse(designacion.sin_inicio)
        self.assertEqual(designacion.desde_texto, "01/03/2026")

    def test_el_formulario_rechaza_un_texto_cualquiera(self):
        from .forms import NuevaDesignacionForm

        form = NuevaDesignacionForm(self.datos_designacion(desde="ayer"))
        self.assertFalse(form.is_valid())
        self.assertIn("desde", form.errors)

    def test_al_editar_se_muestran_las_cadenas_especiales(self):
        from .forms import NuevaDesignacionForm

        designacion = NuevaDesignacionForm(self.datos_designacion())
        designacion.is_valid()
        designacion = designacion.save()
        form = NuevaDesignacionForm(instance=designacion)
        self.assertIn("SIN INICIO", str(form["desde"]))
        self.assertIn("SIN TERMINO", str(form["hasta"]))

    def test_la_pantalla_muestra_sin_inicio_y_sin_termino(self):
        Designacion.objects.create(
            persona=self.persona, cargo=self.cargo,
            desde=date(2026, 3, 1), sin_inicio=True,
        )
        respuesta = self.cliente.get(self.url, {"dni": self.persona.pk})
        self.assertContains(respuesta, "SIN INICIO")
        self.assertContains(respuesta, "SIN TERMINO")

    # ── RF-06: CSV con confirmación, horarios y vigencias especiales ──

    def test_la_vista_previa_no_guarda_nada(self):
        respuesta = self.cliente.post(
            self.url,
            {
                "accion": "importar_csv",
                "archivo": self.csv(
                    "dni,apellido_nombre,cargo_codigo,desde\n"
                    "31000001,Nuevo Uno,PROF,2026-03-01\n"
                    "31000002,Nuevo Dos,NOEXISTE,2026-03-01\n"
                ),
            },
        )
        self.assertContains(respuesta, "Todavía no se guardó nada")
        self.assertEqual(respuesta.context["csv_pendiente"]["validas"], 1)
        self.assertEqual(len(respuesta.context["csv_pendiente"]["rechazos"]), 1)
        self.assertContains(respuesta, "No existe el cargo")
        self.assertFalse(Persona.objects.filter(pk="31000001").exists())
        self.assertFalse(Persona.objects.filter(pk="31000002").exists())
        self.assertEqual(ImportacionPersonalError.objects.count(), 0)

    def test_vista_previa_muestra_y_confirma_un_legajo_sin_designacion(self):
        respuesta = self.cliente.post(
            self.url,
            {
                "accion": "importar_csv",
                "archivo": self.csv(
                    "dni,nombre_apellido,sexo,email\n"
                    '31000003,"GOMEZ, ANA",F,ana@example.com\n'
                ),
            },
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Solo legajo")
        self.assertContains(respuesta, "31000003")
        self.assertFalse(Persona.objects.filter(pk="31000003").exists())

        confirmacion = self.cliente.post(
            self.url, {"accion": "confirmar_csv"}, follow=True
        )
        self.assertContains(confirmacion, "1 filas importadas")
        persona = Persona.objects.get(pk="31000003")
        self.assertEqual(persona.apellido_nombre, "GOMEZ, ANA")
        self.assertFalse(Designacion.objects.filter(persona=persona).exists())

    def test_importa_legajo_y_designacion_desde_la_misma_fila_csv(self):
        respuesta = self.cliente.post(
            self.url,
            {
                "accion": "importar_csv",
                "archivo": self.csv(
                    "dni,nombre_apellido,cargo_codigo,situacion_revista,desde,hasta,"
                    "horas_lun\n"
                    '31000004,"LOPEZ, MARIA",PROF,TIT,2026-03-01,2026-12-31,3\n'
                ),
            },
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Legajo y designación")
        self.assertFalse(Persona.objects.filter(pk="31000004").exists())
        self.cliente.post(self.url, {"accion": "confirmar_csv"})

        persona = Persona.objects.get(pk="31000004")
        designacion = Designacion.objects.get(persona=persona)
        self.assertEqual(persona.apellido_nombre, "LOPEZ, MARIA")
        self.assertEqual(designacion.cargo, self.cargo)
        self.assertEqual(
            designacion.horarios.get(dia=Horario.Dia.LUNES).horas_catedra,
            3,
        )

    def test_importa_filas_personales_y_de_designacion_independientemente(self):
        self.cliente.post(
            self.url,
            {
                "accion": "importar_csv",
                "archivo": self.csv(
                    "dni,nombre_apellido,cargo_codigo,situacion_revista,desde\n"
                    "31000005,SOLO UNO,,,\n"
                    "31000006,CON CARGO,PROF,TIT,2026-03-01\n"
                ),
            },
        )
        respuesta = self.cliente.post(
            self.url, {"accion": "confirmar_csv"}, follow=True
        )

        self.assertContains(respuesta, "2 filas importadas")
        self.assertTrue(Persona.objects.filter(pk="31000005").exists())
        self.assertFalse(
            Designacion.objects.filter(persona_id="31000005").exists()
        )
        self.assertEqual(
            Designacion.objects.filter(persona_id="31000006").count(),
            1,
        )

    def test_importa_csv_mayor_a_cinco_megabytes(self):
        contenido = (
            "dni,nombre_apellido\n31000008,AGENTE\n"
            + "\n" * (5 * 1024 * 1024 + 1)
        )
        archivo = self.csv(contenido)

        self.assertGreater(archivo.size, 5 * 1024 * 1024)
        self.assertEqual(_procesar_csv(archivo), (1, 0))
        self.assertEqual(
            Persona.objects.get(pk="31000008").apellido_nombre,
            "AGENTE",
        )

    def test_materia_repetida_en_carreras_distintas_se_incluye_en_licencia(self):
        from licencias.licencia_docente import materias_afectadas

        carrera_a = Carrera.objects.create(nombre="Carrera A")
        carrera_b = Carrera.objects.create(nombre="Carrera B")
        url_catalogo = reverse("personal:catalogos") + "?seccion=espacios"
        # La materia se carga UNA sola vez, marcada en las dos carreras.
        respuesta = self.cliente.post(
            url_catalogo,
            {
                "accion": "guardar",
                "nombre": "Matemática",
                "carreras": [carrera_a.pk, carrera_b.pk],
                "activo": "on",
            },
        )
        self.assertRedirects(respuesta, url_catalogo)
        materia = EspacioCurricular.objects.get(nombre="Matemática")
        self.assertEqual(
            set(materia.carreras.values_list("pk", flat=True)),
            {carrera_a.pk, carrera_b.pk},
        )
        titular = Designacion.objects.create(
            persona=self.persona,
            cargo=self.cargo,
            espacio_curricular=materia,
            carrera=carrera_a,
            situacion_revista=Designacion.Situacion.TITULAR,
            desde=date(2026, 3, 1),
        )
        suplente = Designacion.objects.create(
            persona=self.persona,
            cargo=self.cargo,
            espacio_curricular=materia,
            carrera=carrera_b,
            situacion_revista=Designacion.Situacion.SUPLENTE,
            desde=date(2026, 3, 1),
        )
        for designacion in (titular, suplente):
            Horario.objects.create(
                designacion=designacion,
                dia=Horario.Dia.LUNES,
                horas_catedra=2,
            )

        afectadas = materias_afectadas(
            self.persona, date(2026, 3, 9), date(2026, 3, 9)
        )

        self.assertEqual(len(afectadas), 2)
        self.assertEqual(
            {
                (
                    item["designacion"].carrera.nombre,
                    item["situacion"],
                )
                for item in afectadas
            },
            {("Carrera A", "Titular"), ("Carrera B", "Suplente")},
        )
        self.assertTrue(
            all(item["dias"] == [date(2026, 3, 9)] for item in afectadas)
        )

    def test_busqueda_de_designaciones_muestra_la_misma_materia_por_carrera(self):
        carrera_a = Carrera.objects.create(nombre="Carrera A")
        carrera_b = Carrera.objects.create(nombre="Carrera B")
        materia = EspacioCurricular.objects.create(nombre="Matemática")
        materia.carreras.add(carrera_a, carrera_b)
        for carrera, situacion in (
            (carrera_a, Designacion.Situacion.TITULAR),
            (carrera_b, Designacion.Situacion.SUPLENTE),
        ):
            Designacion.objects.create(
                persona=self.persona,
                cargo=self.cargo,
                espacio_curricular=materia,
                carrera=carrera,
                situacion_revista=situacion,
                desde=date(2026, 3, 1),
            )

        respuesta = self.cliente.get(
            reverse("inicio_personal"), {"q": self.persona.dni}
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(len(respuesta.context["designaciones"]), 2)
        self.assertContains(respuesta, "Carrera A")
        self.assertContains(respuesta, "Carrera B")
        self.assertContains(respuesta, "Matemática")

        autocomplete = self.cliente.get(
            reverse("personal:designaciones_autocompletar"),
            {"q": self.persona.dni},
        )
        self.assertEqual(autocomplete.status_code, 200)
        self.assertEqual(
            {item["carrera"] for item in autocomplete.json()["resultados"]},
            {"Carrera A", "Carrera B"},
        )

    def test_csv_excel_con_separador_punto_y_coma(self):
        respuesta = self.cliente.post(
            self.url,
            {
                "accion": "importar_csv",
                "archivo": self.csv(
                    "dni;nombre_apellido;email\n"
                    "31000007;AGENTE CSV;agente@example.com\n"
                ),
            },
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context["csv_pendiente"]["validas"], 1)
        self.cliente.post(self.url, {"accion": "confirmar_csv"})
        self.assertTrue(Persona.objects.filter(pk="31000007").exists())

    def test_csv_carga_campos_personales_y_de_designacion_documentados(self):
        archivo = self.csv(
            "dni,nombre_apellido,fecha_nacimiento,estado_civil,nacionalidad,"
            "telefono,email,domicilio_calle,barrio,localidad,codigo_postal,"
            "provincia,cargo_codigo,situacion_revista,anio_curso,division_seccion,"
            "turno,hs_catedra,desde,hasta,norma_tipo,norma_numero,norma_anio,"
            "organismo_emisor,pof,anio_pof,novedad,disp_alta_nro,sello_regional_as,"
            "observaciones,horas_lun\n"
            "31000010,\"PEREZ, ANA\",1990-04-15,Soltera,Argentina,123,"
            "ana@example.com,Calle 1,Centro,Ciudad,1000,Provincia,PROF,TIT,"
            "1,A,M,2,2026-03-01,2026-12-31,Resolución,123,2026,Ministerio,"
            "POF 1,2026,Alta,88,Regional,Observación,2\n"
        )

        total, rechazadas = _procesar_csv(archivo)

        self.assertEqual((total, rechazadas), (1, 0))
        persona = Persona.objects.get(pk="31000010")
        self.assertEqual(persona.fecha_nacimiento, date(1990, 4, 15))
        self.assertEqual(persona.email, "ana@example.com")
        designacion = Designacion.objects.get(persona=persona)
        self.assertEqual(designacion.turno, "M")
        self.assertEqual(designacion.hs_catedra, 2)
        self.assertEqual(designacion.norma_numero, "123")
        self.assertEqual(designacion.norma_anio, 2026)
        self.assertEqual(designacion.pof, "POF 1")
        self.assertEqual(
            designacion.horarios.get(dia=Horario.Dia.LUNES).horas_catedra,
            2,
        )

    def test_columnas_desconocidas_se_informan_antes_de_importar(self):
        respuesta = self.cliente.post(
            self.url,
            {
                "accion": "importar_csv",
                "archivo": self.csv("dni,nombre_completo\n31000008,AGENTE\n"),
            },
            follow=True,
        )

        self.assertContains(respuesta, "Columnas no reconocidas: nombre_completo")
        self.assertFalse(Persona.objects.filter(pk="31000008").exists())

    def test_descargar_plantilla_csv_requiere_permiso_de_importacion(self):
        respuesta = self.cliente.get(
            reverse("personal:plantilla_importacion_csv")
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("text/csv", respuesta["Content-Type"])
        self.assertIn("nombre_apellido", respuesta.content.decode("utf-8-sig"))

    def test_autocompletar_legajos_requiere_permiso_de_personal(self):
        usuario = get_user_model().objects.create_user(
            username="autocomplete-no-permission",
            password="x",
        )
        cliente = Client()
        cliente.force_login(usuario)

        respuesta = cliente.get(
            reverse("personal:legajos_autocompletar"), {"q": "PEREZ"}
        )

        self.assertEqual(respuesta.status_code, 403)

    def test_autocompletado_permite_buscar_a_usuarios_con_permiso_de_designacion(self):
        usuario = get_user_model().objects.create_user(
            username="autocomplete-designacion-permission",
            password="x",
        )
        usuario.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="personal",
                codename="add_designacion",
            )
        )
        cliente = Client()
        cliente.force_login(usuario)

        respuesta = cliente.get(
            reverse("personal:legajos_autocompletar"),
            {"q": self.persona.dni},
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()["resultados"][0]["dni"], self.persona.dni)

    def test_listado_incluye_agentes_sin_designaciones(self):
        Persona.objects.create(
            dni="31000009",
            apellido_nombre="Agente sin cargos",
        )

        respuesta = self.cliente.get(self.url)

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Listado de agentes")
        self.assertContains(respuesta, "31000009")
        self.assertContains(respuesta, "Agente sin cargos")

    def test_formulario_persona_expone_un_solo_campo_de_nombre(self):
        form = PersonaForm()

        campos_nombre = {
            "apellido",
            "nombres",
            "apellido_nombre",
        }.intersection(form.fields)
        self.assertEqual(campos_nombre, {"apellido_nombre"})

    def test_cancelar_descarta_la_importacion(self):
        self.cliente.post(
            self.url,
            {
                "accion": "importar_csv",
                "archivo": self.csv("dni,apellido_nombre\n31000001,Nuevo Uno\n"),
            },
        )
        self.cliente.post(self.url, {"accion": "cancelar_csv"})
        respuesta = self.cliente.post(self.url, {"accion": "confirmar_csv"}, follow=True)
        self.assertContains(respuesta, "No hay ninguna importación pendiente")
        self.assertFalse(Persona.objects.filter(pk="31000001").exists())

    def test_confirmar_importa_horarios_y_vigencias_especiales(self):
        self.cliente.post(
            self.url,
            {
                "accion": "importar_csv",
                "archivo": self.csv(
                    "dni,apellido_nombre,cargo_codigo,situacion_revista,desde,hasta,"
                    "horas_lun,horas_mie,horas_vie,norma_tipo,observaciones\n"
                    "31000001,Nuevo Uno,PROF,TITULAR,SIN INICIO,SIN TERMINO,"
                    "2,3,0,Resolución,Alta por CSV\n"
                ),
            },
        )
        respuesta = self.cliente.post(self.url, {"accion": "confirmar_csv"}, follow=True)
        self.assertContains(respuesta, "1 filas importadas")

        designacion = Designacion.objects.get(persona_id="31000001")
        self.assertTrue(designacion.sin_inicio)
        self.assertIsNone(designacion.hasta)
        self.assertEqual(designacion.norma_tipo, "Resolución")
        self.assertEqual(designacion.observaciones, "Alta por CSV")
        self.assertEqual(
            {h.dia: h.horas_catedra for h in designacion.horarios.all()},
            {"LUN": 2, "MIE": 3},
        )

    def test_el_csv_rechaza_un_instrumento_que_no_esta_en_el_catalogo(self):
        archivo = self.csv(
            "dni,cargo_codigo,desde,norma_tipo\n30123456,PROF,2026-03-01,Papelito\n"
        )
        total, rechazadas = _procesar_csv(archivo)
        self.assertEqual((total, rechazadas), (1, 1))
        self.assertIn(
            "tipo de instrumento legal",
            ImportacionPersonalError.objects.get().motivo_error,
        )

    def test_el_csv_detecta_un_duplicado_dentro_del_mismo_archivo(self):
        archivo = self.csv(
            "dni,cargo_codigo,desde\n"
            "30123456,PROF,2026-03-01\n"
            "30123456,PROF,2026-03-01\n"
        )
        total, rechazadas = _procesar_csv(archivo)
        self.assertEqual((total, rechazadas), (2, 1))
        self.assertEqual(Designacion.objects.filter(persona=self.persona).count(), 1)


class CodigosNumericosDeCargoTests(TestCase):
    """Los códigos de cargo son los numéricos oficiales (150, 155, 165, 166)."""

    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            username="cargos-numericos", password="test-password"
        )
        self.usuario.user_permissions.add(
            Permission.objects.get(codename="change_cargo")
        )
        self.cliente = Client()
        self.cliente.force_login(self.usuario)
        self.url = reverse("personal:catalogos") + "?seccion=cargos"

    def test_la_migracion_crea_los_cargos_oficiales(self):
        self.assertEqual(
            dict(
                Cargo.objects.filter(codigo__in=["150", "155", "165", "166"])
                .values_list("codigo", "descripcion")
            ),
            {
                "150": "Secretaría",
                "155": "Director de Estudio",
                "165": "Bedel",
                "166": "Horas cátedra",
            },
        )

    def test_el_codigo_con_letras_se_rechaza(self):
        cargo = Cargo(codigo="HC", descripcion="Horas cátedra")
        with self.assertRaises(ValidationError):
            cargo.full_clean()

        respuesta = self.cliente.post(
            self.url,
            {"accion": "guardar", "codigo": "HC", "descripcion": "Prueba"},
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "debe ser numérico")
        self.assertFalse(Cargo.objects.filter(codigo="HC").exists())

    def test_el_codigo_numerico_se_guarda(self):
        respuesta = self.cliente.post(
            self.url,
            {"accion": "guardar", "codigo": "170", "descripcion": "Preceptor",
             "activo": "on"},
        )
        self.assertRedirects(respuesta, self.url)
        self.assertTrue(Cargo.objects.filter(codigo="170").exists())

    def test_al_editar_no_se_puede_cambiar_el_codigo(self):
        respuesta = self.cliente.post(
            self.url,
            {"accion": "guardar", "objeto_id": "166", "codigo": "999",
             "descripcion": "Horas cátedra (editado)", "es_docente": "on",
             "activo": "on"},
        )
        self.assertRedirects(respuesta, self.url)
        self.assertFalse(Cargo.objects.filter(codigo="999").exists())
        self.assertEqual(
            Cargo.objects.get(codigo="166").descripcion, "Horas cátedra (editado)"
        )


class MateriaEnVariasCarrerasTests(TestCase):
    """Una materia se carga una vez y puede estar en varias carreras."""

    def setUp(self):
        self.software = Carrera.objects.create(nombre="Software")
        self.gestion = Carrera.objects.create(nombre="Gestión")
        self.higiene = Carrera.objects.create(nombre="Higiene")
        self.ingles = EspacioCurricular.objects.create(nombre="Inglés")
        self.ingles.carreras.add(self.software, self.gestion)
        self.persona = Persona.objects.create(dni="30999111", apellido_nombre="PÉREZ, Ana")
        self.cargo = Cargo.objects.get(codigo="166")

    def designacion(self, **datos):
        datos.setdefault("espacio_curricular", self.ingles)
        return Designacion(
            persona=self.persona,
            cargo=self.cargo,
            situacion_revista=Designacion.Situacion.TITULAR,
            desde=date(2026, 3, 1),
            **datos,
        )

    def test_misma_materia_en_dos_carreras_con_dos_designaciones(self):
        for carrera in (self.software, self.gestion):
            designacion = self.designacion(carrera=carrera)
            designacion.full_clean()
            designacion.save()
        self.assertEqual(EspacioCurricular.objects.filter(nombre="Inglés").count(), 1)
        self.assertEqual(
            set(self.ingles.designaciones.values_list("carrera__nombre", flat=True)),
            {"Software", "Gestión"},
        )

    def test_materia_con_varias_carreras_exige_indicar_la_carrera(self):
        with self.assertRaises(ValidationError) as error:
            self.designacion().full_clean()
        self.assertIn("carrera", error.exception.message_dict)

    def test_no_acepta_una_carrera_que_no_tiene_la_materia(self):
        with self.assertRaises(ValidationError) as error:
            self.designacion(carrera=self.higiene).full_clean()
        self.assertIn("carrera", error.exception.message_dict)

    def test_materia_de_una_sola_carrera_la_completa_sola(self):
        ergonomia = EspacioCurricular.objects.create(nombre="Ergonomía")
        ergonomia.carreras.add(self.higiene)
        designacion = self.designacion(espacio_curricular=ergonomia)
        designacion.save()
        self.assertEqual(designacion.carrera, self.higiene)

    def test_cargar_una_materia_existente_le_suma_la_carrera(self):
        from .forms import EspacioCurricularForm

        form = EspacioCurricularForm(
            data={"nombre": "  inglés ", "carreras": [self.higiene.pk], "activo": "on"}
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        self.assertEqual(EspacioCurricular.objects.filter(nombre__iexact="inglés").count(), 1)
        self.assertEqual(
            set(self.ingles.carreras.values_list("nombre", flat=True)),
            {"Software", "Gestión", "Higiene"},
        )
        self.assertIn("Higiene", form.aviso)

    def test_sumar_carreras_no_desactiva_la_materia_existente(self):
        from .forms import EspacioCurricularForm

        form = EspacioCurricularForm(data={"nombre": "Inglés", "carreras": [self.higiene.pk]})
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.ingles.refresh_from_db()
        self.assertTrue(self.ingles.activo)

    def test_no_se_quita_una_carrera_con_designaciones_activas(self):
        from .forms import EspacioCurricularForm

        designacion = self.designacion(carrera=self.gestion)
        designacion.save()
        form = EspacioCurricularForm(
            data={"nombre": "Inglés", "carreras": [self.software.pk], "activo": "on"},
            instance=self.ingles,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("Gestión", str(form.errors["carreras"]))

        # Dada de baja la designación, la carrera ya se puede quitar.
        designacion.activo = False
        designacion.save()
        form = EspacioCurricularForm(
            data={"nombre": "Inglés", "carreras": [self.software.pk], "activo": "on"},
            instance=self.ingles,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(list(self.ingles.carreras.all()), [self.software])

    def test_renombrar_con_el_nombre_de_otra_materia_se_rechaza(self):
        from .forms import EspacioCurricularForm

        otra = EspacioCurricular.objects.create(nombre="Francés")
        otra.carreras.add(self.higiene)
        form = EspacioCurricularForm(
            data={"nombre": "Inglés", "carreras": [self.higiene.pk], "activo": "on"},
            instance=otra,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("nombre", form.errors)

    def test_csv_pide_la_carrera_si_la_materia_esta_en_varias(self):
        def csv(contenido):
            return SimpleUploadedFile(
                "personal.csv", contenido.encode("utf-8"), content_type="text/csv"
            )

        total, rechazadas = _procesar_csv(csv(
            "dni,cargo_codigo,espacio_curricular,desde\n"
            "30999111,166,Inglés,2026-03-01\n"
        ))
        self.assertEqual((total, rechazadas), (1, 1))
        self.assertIn("más de una carrera", ImportacionPersonalError.objects.get().motivo_error)

        total, rechazadas = _procesar_csv(csv(
            "dni,cargo_codigo,espacio_curricular,carrera,desde\n"
            "30999111,166,Inglés,Gestión,2026-03-01\n"
        ))
        self.assertEqual((total, rechazadas), (1, 0))
        self.assertEqual(
            Designacion.objects.get(persona=self.persona).carrera, self.gestion
        )


class MigracionMateriasRepetidasTests(TransactionTestCase):
    """La migración 0007 une las materias repetidas en distintas carreras."""

    # Restaura los datos que crean las migraciones (cargos, marcas, roles)
    # para los tests que corran después de este.
    serialized_rollback = True
    antes = [("personal", "0006_codigos_numericos_de_cargo")]
    despues = [("personal", "0007_materia_en_varias_carreras")]

    def tearDown(self):
        # Deja la base de prueba en la última migración para los demás tests.
        call_command("migrate", verbosity=0)
        super().tearDown()

    def test_une_materias_repetidas_y_conserva_la_carrera_de_cada_designacion(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        ejecutor = MigrationExecutor(connection)
        ejecutor.migrate(self.antes)
        viejas = ejecutor.loader.project_state(self.antes).apps
        CarreraV = viejas.get_model("personal", "Carrera")
        EspacioV = viejas.get_model("personal", "EspacioCurricular")
        PersonaV = viejas.get_model("personal", "Persona")
        DesignacionV = viejas.get_model("personal", "Designacion")

        software = CarreraV.objects.create(nombre="Software")
        gestion = CarreraV.objects.create(nombre="Gestión")
        ingles_a = EspacioV.objects.create(nombre="Inglés", carrera=software)
        ingles_b = EspacioV.objects.create(nombre="INGLES ", carrera=gestion)
        persona = PersonaV.objects.create(dni="30999222", apellido_nombre="RUIZ, Juan")
        for espacio in (ingles_a, ingles_b):
            DesignacionV.objects.create(
                persona=persona, cargo_id="166", espacio_curricular=espacio,
                desde=date(2026, 3, 1),
            )

        ejecutor = MigrationExecutor(connection)
        ejecutor.loader.build_graph()
        ejecutor.migrate(self.despues)
        nuevas = ejecutor.loader.project_state(self.despues).apps
        EspacioN = nuevas.get_model("personal", "EspacioCurricular")
        DesignacionN = nuevas.get_model("personal", "Designacion")

        materias = list(EspacioN.objects.all())
        self.assertEqual(len(materias), 1)
        self.assertEqual(
            set(materias[0].carreras.values_list("nombre", flat=True)),
            {"Software", "Gestión"},
        )
        self.assertEqual(
            sorted(
                DesignacionN.objects.values_list(
                    "espacio_curricular_id", "carrera__nombre"
                )
            ),
            sorted([(materias[0].pk, "Software"), (materias[0].pk, "Gestión")]),
        )


# ───────────── Designación: suplencia, plazo indeterminado y horas cátedra ─────────────

class SuplenciaYHorasNombradasTests(TestCase):
    """
    La suplencia sale de la situación de revista (Suplente) y el plazo
    indeterminado de escribir SIN TERMINO: ya no hay casillas aparte ni el
    campo Especialidad en el formulario (las columnas siguen en la base). El
    horario semanal tiene que sumar las horas cátedra nombradas.
    """

    def setUp(self):
        self.cargo = Cargo.objects.create(codigo="PROF", descripcion="Profesor")
        self.persona = Persona.objects.create(dni="30123456", apellido_nombre="PEREZ, JUAN")

    def formulario(self, instance=None, **cambios):
        datos = {
            "persona": self.persona.pk,
            "cargo": self.cargo.pk,
            "situacion_revista": "TIT",
            "desde": "2026-03-01",
            "hasta": "",
            "hs_catedra": "4",
            "horas_lun": "2",
            "horas_mie": "2",
        }
        datos.update(cambios)
        return NuevaDesignacionForm(datos, instance=instance)

    def guardar(self, **cambios):
        form = self.formulario(**cambios)
        self.assertTrue(form.is_valid(), form.errors)
        return form.save()

    # ── Campos que ya no están ──
    def test_el_formulario_no_tiene_especialidad_ni_casillas(self):
        for campo in ("especialidad", "es_suplencia", "plazo_indeterminado"):
            self.assertNotIn(campo, NuevaDesignacionForm().fields)
            self.assertNotIn(campo, DesignacionForm().fields)

    def test_las_pantallas_no_los_muestran(self):
        cliente = Client()
        cliente.force_login(get_user_model().objects.create_superuser("admin-horas", password="x"))
        for respuesta in (
            cliente.get(reverse("personal:nueva_designacion")),
            cliente.get(reverse("personal:gestion_legajos"), {"dni": self.persona.dni}),
        ):
            for nombre in ("especialidad", "es_suplencia", "plazo_indeterminado"):
                self.assertNotContains(respuesta, f'name="{nombre}"')
            self.assertContains(respuesta, 'id="controlHoras"')

    # ── Suplencia y plazo indeterminado ──
    def test_suplente_con_fecha_de_cese(self):
        designacion = self.guardar(situacion_revista="SUP", hasta="2026-07-31")
        self.assertTrue(designacion.es_suplencia)
        self.assertFalse(designacion.plazo_indeterminado)

    def test_suplente_sin_termino_es_de_plazo_indeterminado(self):
        designacion = self.guardar(situacion_revista="SUP", hasta="SIN TERMINO")
        self.assertTrue(designacion.es_suplencia)
        self.assertTrue(designacion.plazo_indeterminado)
        self.assertIsNone(designacion.hasta)

    def test_suplente_sin_fecha_de_cese_se_rechaza_con_un_solo_aviso(self):
        form = self.formulario(situacion_revista="SUP", hasta="")
        self.assertFalse(form.is_valid())
        self.assertEqual(len(form.errors["hasta"]), 1)
        self.assertIn("SIN TERMINO", form.errors["hasta"][0])

    def test_titular_no_es_suplencia(self):
        designacion = self.guardar(situacion_revista="TIT", hasta="SIN TERMINO")
        self.assertFalse(designacion.es_suplencia)
        self.assertFalse(designacion.plazo_indeterminado)

    def test_pasar_de_suplente_a_titular_quita_la_suplencia(self):
        designacion = self.guardar(situacion_revista="SUP", hasta="SIN TERMINO")
        form = self.formulario(instance=designacion, situacion_revista="TIT", hasta="SIN TERMINO")
        self.assertTrue(form.is_valid(), form.errors)
        designacion = form.save()
        self.assertFalse(designacion.es_suplencia)
        self.assertFalse(designacion.plazo_indeterminado)

    def test_solo_un_suplente_reemplaza_a_otra_designacion(self):
        otra = Persona.objects.create(dni="30123499", apellido_nombre="TITULAR, ANA")
        titular = Designacion.objects.create(persona=otra, cargo=self.cargo, desde=date(2026, 3, 1))
        form = self.formulario(situacion_revista="TIT", reemplaza=titular.pk)
        self.assertFalse(form.is_valid())
        self.assertIn("reemplaza", form.errors)

    # ── Horas cátedra ──
    def test_horario_igual_a_las_horas_nombradas_se_guarda(self):
        designacion = self.guardar()
        self.assertEqual(designacion.hs_catedra, 4)
        self.assertEqual(
            dict(designacion.horarios.values_list("dia", "horas_catedra")), {"LUN": 2, "MIE": 2}
        )

    def test_horario_que_no_suma_las_horas_nombradas_se_rechaza(self):
        form = self.formulario(hs_catedra="5")
        self.assertFalse(form.is_valid())
        self.assertIn("suma 4 horas", form.errors["hs_catedra"][0])
        self.assertIn("deben coincidir", form.errors["hs_catedra"][0])

    def test_sin_horas_nombradas_se_rechaza(self):
        form = self.formulario(hs_catedra="")
        self.assertFalse(form.is_valid())
        self.assertIn("Indique las horas cátedra nombradas", form.errors["hs_catedra"][0])

    def test_sin_horario_se_rechaza(self):
        form = self.formulario(horas_lun="0", horas_mie="0")
        self.assertFalse(form.is_valid())
        self.assertIn("suma 0 horas", form.errors["hs_catedra"][0])

    def test_problema_de_horas_de_una_designacion(self):
        designacion = Designacion.objects.create(
            persona=self.persona, cargo=self.cargo, desde=date(2026, 3, 1), hs_catedra=4
        )
        Horario.objects.create(designacion=designacion, dia="LUN", horas_catedra=3)
        self.assertIn("suma 3 horas", designacion.problema_de_horas())
        Horario.objects.create(designacion=designacion, dia="MIE", horas_catedra=1)
        self.assertIsNone(designacion.problema_de_horas())

    # ── Importación CSV ──
    def csv(self, texto):
        return SimpleUploadedFile("personal.csv", texto.encode("utf-8"))

    def test_csv_con_horas_y_horario_distintos_se_rechaza(self):
        total, rechazadas = _procesar_csv(self.csv(
            "dni,cargo_codigo,desde,hs_catedra,horas_lun\n30123456,PROF,2026-03-01,4,2\n"
        ))
        self.assertEqual((total, rechazadas), (1, 1))
        self.assertIn("deben coincidir", ImportacionPersonalError.objects.get().motivo_error)

    def test_csv_con_horario_sin_horas_completa_las_horas_nombradas(self):
        total, rechazadas = _procesar_csv(self.csv(
            "dni,cargo_codigo,desde,horas_lun,horas_jue\n30123456,PROF,2026-03-01,2,3\n"
        ))
        self.assertEqual((total, rechazadas), (1, 0))
        self.assertEqual(Designacion.objects.get(persona=self.persona).hs_catedra, 5)

    def test_csv_suplente_sin_columna_es_suplencia(self):
        total, rechazadas = _procesar_csv(self.csv(
            "dni,cargo_codigo,situacion_revista,desde,hasta\n30123456,PROF,SUP,2026-03-01,2026-07-31\n"
        ))
        self.assertEqual((total, rechazadas), (1, 0))
        self.assertTrue(Designacion.objects.get(persona=self.persona).es_suplencia)


class CsvComoLoGuardaExcelTests(TestCase):
    """RF-06: la importación acepta los archivos tal como los guarda Excel."""

    ENCABEZADO = "dni;nombre_apellido;cargo_codigo;espacio_curricular;situacion_revista;hs_catedra;desde;hasta;horas_lun\n"

    def setUp(self):
        Cargo.objects.get_or_create(codigo="166", defaults={"descripcion": "Horas cátedra"})
        carrera = Carrera.objects.create(nombre="Desarrollo de Software")
        EspacioCurricular.objects.create(nombre="Matemática I").carreras.add(carrera)
        EspacioCurricular.objects.create(nombre="Inglés").carreras.add(carrera)

    def importar(self, texto, codificacion="utf-8"):
        return _procesar_csv(SimpleUploadedFile("personal.csv", texto.encode(codificacion)))

    def motivos(self):
        return [e.motivo_error for e in ImportacionPersonalError.objects.order_by("numero_fila")]

    def test_excel_en_espanol_ansi_con_punto_y_coma_y_fechas_dd_mm_aaaa(self):
        total, rechazadas = self.importar(
            "DNI;Nombre y Apellido;Sexo;fecha_nacimiento;cargo_codigo;espacio_curricular;"
            "situacion_revista;hs_catedra;desde;horas_lun;horas_mie\r\n"
            "30.123.456;MUÑOZ, José;Masculino;15/04/1990;166;Matemática I;Titular;4;"
            "01/03/2026;2;2\r\n",
            codificacion="cp1252",
        )
        self.assertEqual((total, rechazadas), (1, 0), self.motivos())
        persona = Persona.objects.get(pk="30123456")
        self.assertEqual(persona.apellido_nombre, "MUÑOZ, José")
        self.assertEqual(persona.sexo, "M")
        self.assertEqual(persona.fecha_nacimiento, date(1990, 4, 15))
        designacion = Designacion.objects.get(persona=persona)
        self.assertEqual(designacion.situacion_revista, Designacion.Situacion.TITULAR)
        self.assertEqual(designacion.desde, date(2026, 3, 1))
        self.assertEqual(designacion.hs_catedra, 4)

    def test_numeros_que_excel_guarda_con_decimales(self):
        total, rechazadas = self.importar(
            "dni,nombre_apellido,cargo_codigo,espacio_curricular,hs_catedra,desde,horas_lun\n"
            '30123456.0,"PEREZ, Ana",166.0,Matemática I,4.0,2026-03-01,4.0\n'
        )
        self.assertEqual((total, rechazadas), (1, 0), self.motivos())
        self.assertEqual(Designacion.objects.get(persona_id="30123456").hs_catedra, 4)

    def test_renglones_vacios_y_columnas_sin_titulo_se_ignoran(self):
        total, rechazadas = self.importar(
            "dni;nombre_apellido;;\n30123456;PEREZ, Ana;;\n;;;\n\n"
        )
        self.assertEqual((total, rechazadas), (1, 0), self.motivos())

    def test_datos_en_una_columna_sin_titulo_rechazan_la_fila(self):
        total, rechazadas = self.importar("dni;nombre_apellido;\n30123456;PEREZ, Ana;algo\n")
        self.assertEqual((total, rechazadas), (1, 1))
        self.assertIn("columna sin título", self.motivos()[0])

    def test_una_coma_sin_comillas_se_explica(self):
        total, rechazadas = self.importar("dni,nombre_apellido\n30123456,PEREZ, Ana\n")
        self.assertEqual((total, rechazadas), (1, 1))
        self.assertIn("coma sin comillas", self.motivos()[0])

    def test_una_fila_corta_vale_como_celdas_vacias(self):
        total, rechazadas = self.importar('dni,nombre_apellido,email,telefono\n30123456,"PEREZ, Ana"\n')
        self.assertEqual((total, rechazadas), (1, 0), self.motivos())

    def test_el_renglon_sep_de_excel_indica_el_separador(self):
        total, rechazadas = self.importar("sep=;\ndni;nombre_apellido\n30123456;PEREZ, Ana\n")
        self.assertEqual((total, rechazadas), (1, 0), self.motivos())

    def test_el_numero_de_fila_es_el_renglon_del_archivo(self):
        self.importar("dni;nombre_apellido\n30123456;PEREZ, Ana\n\n12AB;MAL\n")
        self.assertEqual(ImportacionPersonalError.objects.get().numero_fila, 4)

    def test_mismo_dni_y_mismo_nombre_en_varias_filas(self):
        total, rechazadas = self.importar(
            self.ENCABEZADO
            + "30123456;PEREZ, Ana;166;Matemática I;TIT;2;2026-03-01;;2\n"
            + "30123456;Ana Pérez;166;Inglés;TIT;3;2026-03-01;;3\n"
        )
        self.assertEqual((total, rechazadas), (2, 0), self.motivos())
        self.assertEqual(Designacion.objects.filter(persona_id="30123456").count(), 2)
        # El nombre escrito de otra forma no pisa el de la primera fila.
        self.assertEqual(Persona.objects.get(pk="30123456").apellido_nombre, "PEREZ, Ana")

    def test_mismo_dni_con_otro_nombre_se_rechaza(self):
        total, rechazadas = self.importar(
            "dni;nombre_apellido\n30123456;PEREZ, Ana\n30123456;GOMEZ, Luis\n"
        )
        self.assertEqual((total, rechazadas), (2, 1))
        self.assertIn("ya aparece en la fila 2", self.motivos()[0])
        self.assertEqual(Persona.objects.get(pk="30123456").apellido_nombre, "PEREZ, Ana")

    def test_dni_invalido_se_explica(self):
        total, rechazadas = self.importar("dni;nombre_apellido\n12AB;PEREZ, Ana\n")
        self.assertEqual((total, rechazadas), (1, 1))
        self.assertIn("entre 7 y 10 números", self.motivos()[0])

    def test_sexo_invalido_se_explica(self):
        self.importar("dni;nombre_apellido;sexo\n30123456;PEREZ, Ana;X\n")
        self.assertIn("debe ser M o F", self.motivos()[0])

    def test_fecha_con_anio_de_dos_cifras_se_rechaza(self):
        self.importar("dni;nombre_apellido;fecha_nacimiento\n30123456;PEREZ, Ana;15/04/90\n")
        self.assertIn("año de 4 cifras", self.motivos()[0])

    def test_situacion_de_revista_invalida_se_explica(self):
        self.importar(self.ENCABEZADO + "30123456;PEREZ, Ana;166;Matemática I;Contratado;2;2026-03-01;;2\n")
        self.assertIn("usá TIT, INT o SUP", self.motivos()[0])

    def test_suplente_sin_fecha_de_cese_pide_sin_termino(self):
        total, rechazadas = self.importar(
            self.ENCABEZADO + "30123456;PEREZ, Ana;166;Matemática I;Suplente;2;2026-03-01;;2\n"
        )
        self.assertEqual((total, rechazadas), (1, 1))
        self.assertIn("SIN TERMINO", self.motivos()[0])

        total, rechazadas = self.importar(
            self.ENCABEZADO + "30123457;GOMEZ, Luis;166;Matemática I;Suplente;2;2026-03-01;SIN TERMINO;2\n"
        )
        self.assertEqual((total, rechazadas), (1, 0))
        self.assertTrue(Designacion.objects.get(persona_id="30123457").plazo_indeterminado)

    def test_la_plantilla_usa_punto_y_coma_para_excel_en_espanol(self):
        usuario = get_user_model().objects.create_user(username="plantilla-csv", password="x")
        usuario.user_permissions.add(Permission.objects.get(codename="add_persona"))
        cliente = Client()
        cliente.force_login(usuario)
        respuesta = cliente.get(reverse("personal:plantilla_importacion_csv"))
        encabezado = respuesta.content.decode("utf-8-sig").splitlines()[0]
        self.assertTrue(encabezado.startswith("dni;nombre_apellido;"))

        # La plantilla, tal cual, se puede volver a importar.
        total, _ = self.importar(encabezado + "\n")
        self.assertEqual(total, 0)
