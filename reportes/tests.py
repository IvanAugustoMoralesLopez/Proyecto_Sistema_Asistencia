from datetime import datetime, time

from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from asistencias.models import EventoAsistencia

from .models import ParametroSistema
from .roles import BEDELIA, SECRETARIA, SUBSECRETARIA
from .signals import BitacoraInalterable


def crear_usuario(username, *codenames):
    usuario = User.objects.create_user(username, password="x")
    permisos = Permission.objects.filter(codename__in=codenames)
    assert permisos.count() == len(set(codenames)), "permiso inexistente"
    usuario.user_permissions.add(*permisos)
    return usuario


class ParametroSistemaTests(TestCase):
    def test_valores_por_defecto(self):
        parametros = ParametroSistema.obtener()
        self.assertEqual(parametros.codigo_oficina, "1452")
        self.assertEqual(parametros.nombre_oficina, "IESETyFP")
        self.assertEqual(parametros.ciclo_lectivo, timezone.localdate().year)

    def test_es_una_unica_fila(self):
        ParametroSistema.obtener()
        ParametroSistema(codigo_oficina="9999").save()
        self.assertEqual(ParametroSistema.objects.count(), 1)
        self.assertEqual(ParametroSistema.obtener().codigo_oficina, "9999")

    def test_vista_requiere_permiso(self):
        url = reverse("reportes:parametros")
        self.assertEqual(self.client.get(url).status_code, 302)  # login
        self.client.force_login(crear_usuario("sin_permiso"))
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_vista_guarda_y_registra_usuario(self):
        usuario = crear_usuario("sub", "gestionar_parametros")
        self.client.force_login(usuario)
        respuesta = self.client.post(
            reverse("reportes:parametros"),
            {"codigo_oficina": "1452", "nombre_oficina": "IESETyFP", "ciclo_lectivo": "2027"},
        )
        self.assertEqual(respuesta.status_code, 302)
        parametros = ParametroSistema.obtener()
        self.assertEqual(parametros.ciclo_lectivo, 2027)
        self.assertEqual(parametros.actualizado_por, usuario)
        evento = EventoAsistencia.objects.get(accion="PARAMETROS")
        self.assertEqual(evento.usuario, usuario)
        self.assertEqual(evento.antes["ciclo_lectivo"], timezone.localdate().year)
        self.assertEqual(evento.despues["ciclo_lectivo"], 2027)

    def test_ciclo_lectivo_invalido(self):
        self.client.force_login(crear_usuario("sub", "gestionar_parametros"))
        respuesta = self.client.post(
            reverse("reportes:parametros"),
            {"codigo_oficina": "1452", "nombre_oficina": "X", "ciclo_lectivo": "1800"},
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["form"].errors)


class RolesTests(TestCase):
    def codenames(self, nombre):
        return set(Group.objects.get(name=nombre).permissions.values_list("codename", flat=True))

    def test_grupos_creados_por_migracion(self):
        self.assertEqual(
            set(Group.objects.values_list("name", flat=True)),
            {BEDELIA, SECRETARIA, SUBSECRETARIA},
        )

    def test_bedelia_no_valida_ni_administra(self):
        permisos = self.codenames(BEDELIA)
        self.assertIn("cerrar_jornada", permisos)
        for prohibido in ("validar_registro", "cerrar_periodo", "ver_bitacora", "gestionar_parametros"):
            self.assertNotIn(prohibido, permisos)

    def test_jerarquia(self):
        bedelia, secretaria, sub = (self.codenames(n) for n in (BEDELIA, SECRETARIA, SUBSECRETARIA))
        self.assertLess(bedelia, secretaria)
        self.assertLess(secretaria, sub)
        self.assertIn("modificar_jornada_cerrada", secretaria)
        self.assertIn("gestionar_parametros", sub)
        self.assertNotIn("gestionar_parametros", secretaria)


class BitacoraTests(TestCase):
    def setUp(self):
        self.url = reverse("reportes:bitacora")
        self.ana = User.objects.create_user("ana", password="x")
        self.beto = User.objects.create_user("beto", password="x")
        self.e1 = EventoAsistencia.objects.create(usuario=self.ana, accion="CREAR")
        self.e2 = EventoAsistencia.objects.create(usuario=self.beto, accion="CERRAR_DIA")
        self.client.force_login(crear_usuario("sec", "ver_bitacora"))

    def test_requiere_permiso(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(crear_usuario("otro"))
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_lista_todo(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(len(respuesta.context["pagina"]), 2)

    def test_filtra_por_usuario_y_accion(self):
        por_usuario = self.client.get(self.url, {"usuario": self.ana.pk})
        self.assertEqual([e.pk for e in por_usuario.context["pagina"]], [self.e1.pk])
        por_accion = self.client.get(self.url, {"accion": "CERRAR_DIA"})
        self.assertEqual([e.pk for e in por_accion.context["pagina"]], [self.e2.pk])

    def test_filtra_por_fechas(self):
        antiguo = timezone.make_aware(datetime.combine(datetime(2026, 1, 10), time(12, 0)))
        EventoAsistencia.objects.filter(pk=self.e1.pk).update(creado_en=antiguo)
        respuesta = self.client.get(self.url, {"desde": "2026-01-10", "hasta": "2026-01-10"})
        self.assertEqual([e.pk for e in respuesta.context["pagina"]], [self.e1.pk])

    def test_rango_invertido_es_error(self):
        respuesta = self.client.get(self.url, {"desde": "2026-02-01", "hasta": "2026-01-01"})
        self.assertTrue(respuesta.context["form"].non_field_errors())


class InalterabilidadTests(TestCase):
    def test_no_se_puede_editar_ni_borrar(self):
        evento = EventoAsistencia.objects.create(accion="CREAR")
        evento.motivo = "cambiado"
        with self.assertRaises(BitacoraInalterable):
            evento.save()
        with self.assertRaises(BitacoraInalterable):
            evento.delete()


# ───────────── RF-19: usuarios y roles ─────────────

from django.core.management import call_command



class UsuariosTests(TestCase):
    def setUp(self):
        self.admin = crear_usuario("sub", "gestionar_usuarios")
        self.client.force_login(self.admin)
        self.datos = {
            "username": "zunilda",
            "first_name": "Zunilda",
            "last_name": "Aquino",
            "email": "z@example.com",
            "is_active": "on",
            "rol": Group.objects.get(name=BEDELIA).pk,
            "password1": "Clave-Segura-2026",
            "password2": "Clave-Segura-2026",
        }

    def test_requiere_permiso(self):
        self.client.force_login(crear_usuario("otro"))
        for nombre in ("usuarios", "usuario_crear"):
            self.assertEqual(self.client.get(reverse(f"reportes:{nombre}")).status_code, 403)

    def test_alta_asigna_rol_y_audita_sin_contrasena(self):
        respuesta = self.client.post(reverse("reportes:usuario_crear"), self.datos)
        self.assertEqual(respuesta.status_code, 302)
        nuevo = User.objects.get(username="zunilda")
        self.assertTrue(nuevo.check_password("Clave-Segura-2026"))
        self.assertEqual(list(nuevo.groups.values_list("name", flat=True)), [BEDELIA])
        evento = EventoAsistencia.objects.get(usuario=self.admin, accion="USUARIO_ALTA")
        self.assertEqual(evento.despues["usuario"], "zunilda")
        self.assertEqual(evento.despues["rol"], BEDELIA)
        self.assertNotIn("Clave", str(evento.despues))
        self.assertNotIn("password", str(evento.despues).lower())

    def test_contrasena_debil_o_distinta(self):
        self.datos.update(password1="123", password2="123")
        self.assertTrue(self.client.post(reverse("reportes:usuario_crear"), self.datos).context["form"].errors)
        self.datos.update(password1="Clave-Segura-2026", password2="otra")
        self.assertIn("password2", self.client.post(reverse("reportes:usuario_crear"), self.datos).context["form"].errors)
        self.assertFalse(User.objects.filter(username="zunilda").exists())

    def test_editar_cambia_solo_el_rol_y_conserva_otros_grupos(self):
        self.client.post(reverse("reportes:usuario_crear"), self.datos)
        usuario = User.objects.get(username="zunilda")
        extra = Group.objects.create(name="Otro")
        usuario.groups.add(extra)

        self.datos.update(rol=Group.objects.get(name=SECRETARIA).pk, password1="", password2="")
        self.client.post(reverse("reportes:usuario_editar", args=[usuario.pk]), self.datos)

        nombres = set(usuario.groups.values_list("name", flat=True))
        self.assertEqual(nombres, {SECRETARIA, "Otro"})
        self.assertTrue(usuario.check_password("Clave-Segura-2026"))  # no se tocó

    def test_no_puede_desactivarse_ni_cambiarse_el_rol_a_si_mismo(self):
        self.admin.groups.add(Group.objects.get(name=SUBSECRETARIA))
        datos = {
            "username": "sub", "first_name": "A", "last_name": "B", "email": "",
            "rol": Group.objects.get(name=BEDELIA).pk,  # intento degradarse
            # is_active ausente = intento desactivarse
        }
        self.client.post(reverse("reportes:usuario_editar", args=[self.admin.pk]), datos)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.assertEqual(list(self.admin.groups.values_list("name", flat=True)), [SUBSECRETARIA])

    def test_superusuario_solo_lo_edita_otro_superusuario(self):
        root = User.objects.create_superuser("root", password="x")
        url = reverse("reportes:usuario_editar", args=[root.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(User.objects.create_superuser("root2", password="x"))
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_edicion_registra_antes_y_despues_en_la_bitacora(self):
        self.client.post(reverse("reportes:usuario_crear"), self.datos)
        usuario = User.objects.get(username="zunilda")
        self.datos.update(
            rol=Group.objects.get(name=SECRETARIA).pk,
            last_name="Aquino de Pérez",
            password1="Otra-Clave-2026",
            password2="Otra-Clave-2026",
        )
        self.client.post(reverse("reportes:usuario_editar", args=[usuario.pk]), self.datos)

        evento = EventoAsistencia.objects.get(accion="USUARIO_EDITAR")
        self.assertEqual(evento.antes["rol"], BEDELIA)
        self.assertEqual(evento.despues["rol"], SECRETARIA)
        self.assertEqual(evento.antes["apellido"], "Aquino")
        self.assertEqual(evento.despues["apellido"], "Aquino de Pérez")
        self.assertEqual(evento.despues["contraseña"], "restablecida")
        self.assertNotIn("Otra-Clave", str(evento.despues))

    def test_eventos_de_usuario_se_ven_en_la_pantalla_de_bitacora(self):
        self.client.post(reverse("reportes:usuario_crear"), self.datos)
        self.client.force_login(crear_usuario("sec", "ver_bitacora"))
        respuesta = self.client.get(reverse("reportes:bitacora"), {"accion": "USUARIO_ALTA"})
        evento = list(respuesta.context["pagina"])[0]
        self.assertEqual(evento.objetivo, "Usuario zunilda")

    def test_listado_filtra_por_rol(self):
        self.client.post(reverse("reportes:usuario_crear"), self.datos)
        respuesta = self.client.get(reverse("reportes:usuarios"), {"rol": BEDELIA})
        self.assertEqual([u.username for u in respuesta.context["usuarios"]], ["zunilda"])


class SincronizarRolesTests(TestCase):
    def test_restablece_permisos_modificados(self):
        grupo = Group.objects.get(name=BEDELIA)
        grupo.permissions.clear()
        call_command("sincronizar_roles", verbosity=0)
        self.assertIn("cerrar_jornada", grupo.permissions.values_list("codename", flat=True))


# ───────────── RF-17: consultas ─────────────

from datetime import date

from licencias.models import LicenciaArticulo, LicenciaOtorgada
from personal.models import Cargo, Carrera, Designacion, EspacioCurricular, Persona


class ConsultasTests(TestCase):
    def setUp(self):
        self.url = reverse("reportes:consultas")
        cargo = Cargo.objects.create(codigo="166", descripcion="Hs cátedra")
        self.sistemas = Carrera.objects.create(nombre="Desarrollo de Software")
        self.redes = Carrera.objects.create(nombre="Redes")
        art_salud = LicenciaArticulo.objects.create(
            cod_licencia="01.02.01", articulo="309 B-2", tipo_licencia="Enfermedad",
            sit_rev="Titular", goce_haberes="Con goce", autoridad="Dirección", plazo="30 días",
        )
        art_part = LicenciaArticulo.objects.create(
            cod_licencia="02.01.01", articulo="312", tipo_licencia="Razones particulares",
            sit_rev="Titular", goce_haberes="Con goce", autoridad="Dirección", plazo="6 días",
        )

        def designar(dni, nombre, carrera):
            persona = Persona.objects.create(dni=dni, apellido_nombre=nombre)
            espacio = EspacioCurricular.objects.create(nombre=f"Mat {dni}", carrera=carrera)
            return Designacion.objects.create(
                persona=persona, cargo=cargo, espacio_curricular=espacio, desde=date(2026, 3, 1)
            )

        self.d_acosta = designar("11111111", "ACOSTA, FELICIANO", self.sistemas)
        self.d_benitez = designar("22222222", "BENITEZ, MARTA", self.redes)

        self.l1 = LicenciaOtorgada.objects.create(
            designacion=self.d_acosta, articulo=art_salud, sit_rev="TIT",
            disp_tipo="Disposición", disp_numero="12", disp_anio=2026,
            justifica=True, desde=date(2026, 6, 1), hasta=date(2026, 6, 30),
        )
        self.l2 = LicenciaOtorgada.objects.create(
            designacion=self.d_benitez, articulo=art_part, sit_rev="TIT",
            desde=date(2026, 8, 10), hasta=None,  # licencia abierta
        )
        self.client.force_login(crear_usuario("bedel", "consultar_licencias"))

    def ids(self, **filtros):
        respuesta = self.client.get(self.url, filtros)
        self.assertEqual(respuesta.status_code, 200)
        return {lic.pk for lic in respuesta.context["pagina"]}

    def test_requiere_permiso(self):
        self.client.force_login(crear_usuario("sin"))
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_sin_filtros_lista_todo(self):
        self.assertEqual(self.ids(), {self.l1.pk, self.l2.pk})

    def test_filtros_simples(self):
        self.assertEqual(self.ids(dni="11.111"), {self.l1.pk})
        self.assertEqual(self.ids(apellido="benitez"), {self.l2.pk})
        self.assertEqual(self.ids(carrera=self.redes.pk), {self.l2.pk})
        self.assertEqual(self.ids(tipo_licencia="Enfermedad"), {self.l1.pk})
        self.assertEqual(self.ids(disp_tipo="disposición", disp_numero="12", disp_anio="2026"), {self.l1.pk})
        self.assertEqual(self.ids(justifica="si"), {self.l1.pk})
        self.assertEqual(self.ids(justifica="pendiente"), {self.l2.pk})

    def test_rango_de_fechas_superpuesto_y_licencia_abierta(self):
        self.assertEqual(self.ids(desde="2026-06-15", hasta="2026-06-20"), {self.l1.pk})
        # la abierta (sin hasta) aparece en cualquier rango posterior a su inicio
        self.assertEqual(self.ids(desde="2026-12-01", hasta="2026-12-31"), {self.l2.pk})
        self.assertEqual(self.ids(desde="2026-07-01", hasta="2026-07-31"), set())

    def test_filtros_combinados(self):
        self.assertEqual(self.ids(carrera=self.sistemas.pk, tipo_licencia="Razones particulares"), set())

    def test_rango_invertido_no_filtra_y_muestra_error(self):
        respuesta = self.client.get(self.url, {"desde": "2026-02-01", "hasta": "2026-01-01"})
        self.assertTrue(respuesta.context["form"].non_field_errors())

    def test_exportar_csv_respeta_filtros(self):
        respuesta = self.client.get(self.url, {"dni": "1111", "exportar": "csv"})
        self.assertEqual(respuesta["Content-Type"], "text/csv; charset=utf-8")
        texto = respuesta.content.decode("utf-8-sig")
        self.assertIn("ACOSTA", texto)
        self.assertNotIn("BENITEZ", texto)
        self.assertIn("Disposición 12/2026", texto)


# ───────────── selectors: se prueban sin pasar por HTTP ─────────────

from .selectors import buscar_licencias, texto_instrumento


class SelectorsTests(ConsultasTests):
    def test_buscar_licencias_sin_http(self):
        resultado = buscar_licencias({"carrera": self.sistemas, "justifica": "si"})
        self.assertEqual([lic.pk for lic in resultado], [self.l1.pk])

    def test_buscar_licencias_sin_filtros_devuelve_todo(self):
        self.assertEqual(buscar_licencias().count(), 2)

    def test_texto_instrumento(self):
        self.assertEqual(texto_instrumento(self.l1), "Disposición 12/2026")
        self.assertEqual(texto_instrumento(self.l2), "—")


# ───────────── RF-17: filtro por materia y consulta unificada ─────────────

from asistencias.models import MarcaAsistencia, RegistroAsistencia

from .selectors import buscar_ausencias, buscar_consulta


class ConsultaUnificadaTests(TestCase):
    """Licencias + ausencias/permisos en una sola pantalla, filtrables por materia."""

    def setUp(self):
        ConsultasTests.setUp(self)  # mismos datos base: 2 docentes, 2 licencias
        inasistencia = MarcaAsistencia.objects.get(codigo="I")
        retirado = MarcaAsistencia.objects.get(codigo="PR")
        presente = MarcaAsistencia.objects.get(codigo="P")
        licencia = MarcaAsistencia.objects.get(codigo="LIC")

        def registro(designacion, fecha, marca, **extra):
            return RegistroAsistencia.objects.create(
                designacion=designacion, fecha=fecha, marca=marca, **extra
            )

        self.a1 = registro(
            self.d_acosta, date(2026, 9, 3), inasistencia,
            horas_inasistidas=4, estado_justificacion="INJUSTIFICADA",
        )
        self.a2 = registro(
            self.d_benitez, date(2026, 9, 10), retirado,
            horas_inasistidas=2, estado_justificacion="EN_TRAMITE", nro_formulario="F-77",
        )
        # No deben aparecer: presente, y día amparado por una licencia.
        registro(self.d_acosta, date(2026, 9, 4), presente)
        registro(self.d_acosta, date(2026, 6, 10), licencia, horas_inasistidas=4, licencia=self.l1)

    def claves(self, **filtros):
        respuesta = self.client.get(self.url, filtros)
        self.assertEqual(respuesta.status_code, 200)
        return [(f.origen, f.pk) for f in respuesta.context["pagina"]]

    # --- filtro por materia (RF-17) ---
    def test_filtro_por_materia_en_licencias_y_ausencias(self):
        materia = self.d_acosta.espacio_curricular
        self.assertEqual(
            set(self.claves(espacio_curricular=materia.pk)),
            {("Licencia", self.l1.pk), ("Ausencia", self.a1.pk)},
        )
        otra = self.d_benitez.espacio_curricular
        self.assertEqual(
            set(self.claves(espacio_curricular=otra.pk)),
            {("Licencia", self.l2.pk), ("Ausencia", self.a2.pk)},
        )

    def test_materia_de_otra_carrera_es_error(self):
        respuesta = self.client.get(
            self.url,
            {"carrera": self.redes.pk, "espacio_curricular": self.d_acosta.espacio_curricular.pk},
        )
        self.assertIn("espacio_curricular", respuesta.context["form"].errors)

    def test_materia_inactiva_no_se_ofrece(self):
        espacio = self.d_acosta.espacio_curricular
        espacio.activo = False
        espacio.save()
        respuesta = self.client.get(self.url)
        self.assertNotIn(espacio, respuesta.context["form"].fields["espacio_curricular"].queryset)

    # --- consulta unificada ---
    def test_por_defecto_muestra_licencias_y_ausencias(self):
        self.assertEqual(
            set(self.claves()),
            {("Licencia", self.l1.pk), ("Licencia", self.l2.pk),
             ("Ausencia", self.a1.pk), ("Ausencia", self.a2.pk)},
        )

    def test_no_duplica_dias_con_licencia_ni_presentes(self):
        ausencias = [r.pk for r in buscar_ausencias()]
        self.assertEqual(set(ausencias), {self.a1.pk, self.a2.pk})

    def test_filtro_origen(self):
        self.assertEqual({o for o, _ in self.claves(origen="licencias")}, {"Licencia"})
        self.assertEqual({o for o, _ in self.claves(origen="ausencias")}, {"Ausencia"})

    def test_orden_mezclado_por_fecha_descendente(self):
        # a2 (10/9) > a1 (3/9) > l2 (10/8) > l1 (1/6)
        self.assertEqual(
            self.claves(),
            [("Ausencia", self.a2.pk), ("Ausencia", self.a1.pk),
             ("Licencia", self.l2.pk), ("Licencia", self.l1.pk)],
        )

    def test_filtros_de_licencia_excluyen_ausencias(self):
        self.assertEqual(self.claves(tipo_licencia="Enfermedad"), [("Licencia", self.l1.pk)])
        self.assertEqual(self.claves(disp_anio="2026"), [("Licencia", self.l1.pk)])

    def test_filtros_comunes_aplican_a_ausencias(self):
        self.assertEqual(
            set(self.claves(dni="2222", origen="ausencias")), {("Ausencia", self.a2.pk)}
        )
        self.assertEqual(
            self.claves(origen="ausencias", desde="2026-09-05", hasta="2026-09-30"),
            [("Ausencia", self.a2.pk)],
        )
        self.assertEqual(
            self.claves(origen="ausencias", carrera=self.sistemas.pk), [("Ausencia", self.a1.pk)]
        )

    def test_justificacion_en_ausencias(self):
        self.assertEqual(self.claves(origen="ausencias", justifica="no"), [("Ausencia", self.a1.pk)])
        self.assertEqual(self.claves(origen="ausencias", justifica="pendiente"), [("Ausencia", self.a2.pk)])
        self.assertEqual(self.claves(origen="ausencias", justifica="si"), [])

    def test_paginacion_mezclada_sin_perder_ni_repetir_filas(self):
        presente_inasist = MarcaAsistencia.objects.get(codigo="I")
        for dia in range(1, 29):
            RegistroAsistencia.objects.create(
                designacion=self.d_benitez, fecha=date(2026, 10, dia), marca=presente_inasist,
                horas_inasistidas=1, estado_justificacion="INJUSTIFICADA",
            )
        total = 4 + 28
        p1 = self.claves()
        p2 = self.claves(page=2)
        self.assertEqual(len(p1), 25)
        self.assertEqual(len(p2), total - 25)
        self.assertEqual(len(set(p1) | set(p2)), total)
        self.assertEqual(buscar_consulta().count(), total)

    # --- exportación ---
    def test_csv_incluye_ambos_origenes_y_materia(self):
        respuesta = self.client.get(self.url, {"exportar": "csv"})
        texto = respuesta.content.decode("utf-8-sig")
        self.assertIn("Origen", texto.splitlines()[0])
        self.assertIn("Materia", texto.splitlines()[0])
        self.assertIn("Licencia,11111111", texto)
        self.assertIn("Ausencia,22222222", texto)
        self.assertIn("Formulario F-77", texto)
        self.assertIn("Mat 11111111", texto)

    def test_csv_respeta_filtro_de_materia(self):
        respuesta = self.client.get(
            self.url,
            {"exportar": "csv", "espacio_curricular": self.d_benitez.espacio_curricular.pk},
        )
        texto = respuesta.content.decode("utf-8-sig")
        self.assertIn("BENITEZ", texto)
        self.assertNotIn("ACOSTA", texto)

    def test_csv_neutraliza_formulas(self):
        self.d_acosta.persona.apellido_nombre = "=CMD()"
        self.d_acosta.persona.save()
        texto = self.client.get(self.url, {"exportar": "csv"}).content.decode("utf-8-sig")
        self.assertIn("'=CMD()", texto)
        self.assertNotIn(",=CMD()", texto)


class HistorialAsistenciasPorMateriaTests(TestCase):
    """RF-17 también pide filtrar por materia el historial de asistencias."""

    def setUp(self):
        ConsultasTests.setUp(self)
        inasistencia = MarcaAsistencia.objects.get(codigo="I")
        self.r1 = RegistroAsistencia.objects.create(
            designacion=self.d_acosta, fecha=date(2026, 9, 3), marca=inasistencia,
            horas_inasistidas=4, estado_justificacion="INJUSTIFICADA",
        )
        self.r2 = RegistroAsistencia.objects.create(
            designacion=self.d_benitez, fecha=date(2026, 9, 3), marca=inasistencia,
            horas_inasistidas=4, estado_justificacion="INJUSTIFICADA",
        )

    def test_filtra_por_materia(self):
        url = reverse("asistencia:historial")
        respuesta = self.client.get(
            url, {"espacio_curricular": self.d_benitez.espacio_curricular.pk}
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual([r.pk for r in respuesta.context["pagina"]], [self.r2.pk])


# ───────────── RF-18: alertas de agotamiento ─────────────

from .selectors import calcular_alertas


class AlertasTests(TestCase):
    def setUp(self):
        cargo = Cargo.objects.create(codigo="166", descripcion="Hs cátedra")
        carrera = Carrera.objects.create(nombre="Software")
        espacio = EspacioCurricular.objects.create(nombre="Prog", carrera=carrera)
        persona = Persona.objects.create(dni="33333333", apellido_nombre="CABRAL, ANA")
        self.designacion = Designacion.objects.create(
            persona=persona, cargo=cargo, espacio_curricular=espacio, desde=date(2026, 3, 1)
        )
        self.url = reverse("reportes:alertas")
        self.client.force_login(crear_usuario("bedel", "consultar_licencias"))

    def articulo(self, codigo, tope):
        return LicenciaArticulo.objects.create(
            cod_licencia=f"X.{codigo}", articulo=codigo, tipo_licencia=f"Tipo {codigo}",
            sit_rev="Titular", goce_haberes="Con goce", autoridad="Dirección",
            plazo="-", tope_dias_anual=tope,
        )

    def licencia(self, articulo, desde, hasta):
        return LicenciaOtorgada.objects.create(
            designacion=self.designacion, articulo=articulo, sit_rev="TIT",
            desde=desde, hasta=hasta,
        )

    def test_proximo_y_agotado(self):
        # lun 1/6 a vie 5/6/2026 = 5 días hábiles
        self.licencia(self.articulo("A1", 6), date(2026, 6, 1), date(2026, 6, 5))
        self.licencia(self.articulo("A2", 5), date(2026, 6, 8), date(2026, 6, 12))
        alertas = {a["articulo"]: a for a in calcular_alertas(2026, 80)}
        self.assertEqual(alertas["A1"]["usados"], 5)
        self.assertEqual(alertas["A1"]["restantes"], 1)
        self.assertFalse(alertas["A1"]["agotado"])
        self.assertTrue(alertas["A2"]["agotado"])
        self.assertEqual(alertas["A2"]["restantes"], 0)

    def test_no_avisa_bajo_el_umbral_ni_sin_tope(self):
        self.licencia(self.articulo("B1", 20), date(2026, 6, 1), date(2026, 6, 5))  # 25 %
        self.licencia(self.articulo("B2", None), date(2026, 6, 1), date(2026, 6, 5))  # sin tope
        self.assertEqual(calcular_alertas(2026, 80), [])

    def test_otro_anio_no_cuenta(self):
        self.licencia(self.articulo("C1", 5), date(2025, 6, 2), date(2025, 6, 6))
        self.assertEqual(calcular_alertas(2026, 80), [])
        self.assertEqual(len(calcular_alertas(2025, 80)), 1)

    def test_suma_varias_licencias_del_mismo_articulo(self):
        art = self.articulo("D1", 6)
        self.licencia(art, date(2026, 6, 1), date(2026, 6, 3))   # 3
        self.licencia(art, date(2026, 6, 8), date(2026, 6, 10))  # 3
        (alerta,) = calcular_alertas(2026, 80)
        self.assertEqual(alerta["usados"], 6)
        self.assertTrue(alerta["agotado"])

    def test_vista_requiere_permiso_y_usa_ciclo_lectivo_por_defecto(self):
        self.client.force_login(crear_usuario("sin"))
        self.assertEqual(self.client.get(self.url).status_code, 403)

        self.client.force_login(crear_usuario("bedel2", "consultar_licencias"))
        self.licencia(self.articulo("E1", 5), date(2026, 6, 1), date(2026, 6, 5))
        parametros = ParametroSistema.obtener()
        parametros.ciclo_lectivo = 2026
        parametros.save()
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(len(respuesta.context["alertas"]), 1)

    def test_vista_solo_agotados(self):
        self.licencia(self.articulo("F1", 6), date(2026, 6, 1), date(2026, 6, 5))  # 83 %
        respuesta = self.client.get(self.url, {"anio": 2026, "umbral": 100})
        self.assertEqual(respuesta.context["alertas"], [])


# ───────────── Correcciones de la revisión técnica (A2, M11, B5, B6) ─────────────

from django.contrib import admin as django_admin
from django.test import RequestFactory

from .admin import ParametroSistemaAdmin
from .exportaciones import _texto_seguro, filas_consulta
from .selectors import FilaConsulta


class RolesPersonalLicenciasTests(TestCase):
    """A2: los roles pueden operar las pantallas de Personal y Licencias."""

    def usuario_con_rol(self, nombre_rol):
        usuario = User.objects.create_user(f"u_{nombre_rol}", password="x")
        usuario.groups.add(Group.objects.get(name=nombre_rol))
        self.client.force_login(usuario)
        return usuario

    def codenames(self, nombre):
        return set(Group.objects.get(name=nombre).permissions.values_list("codename", flat=True))

    def test_matriz_por_rol(self):
        bedelia, secretaria, sub = (self.codenames(n) for n in (BEDELIA, SECRETARIA, SUBSECRETARIA))
        self.assertIn("add_licenciaotorgada", bedelia)
        self.assertNotIn("change_persona", bedelia)
        self.assertIn("change_designacion", secretaria)
        self.assertNotIn("change_cargo", secretaria)
        self.assertIn("change_licenciaarticulo", sub)

    def test_bedelia_opera_licencias_pero_no_personal(self):
        self.usuario_con_rol(BEDELIA)
        self.assertEqual(self.client.get(reverse("licencias:listado_licencias_otorgadas")).status_code, 200)
        self.assertEqual(self.client.get(reverse("licencias:nueva_licencia_otorgada")).status_code, 200)
        self.assertEqual(self.client.get(reverse("personal:gestion_legajos")).status_code, 403)

    def test_secretaria_opera_legajos_y_designaciones(self):
        self.usuario_con_rol(SECRETARIA)
        self.assertEqual(self.client.get(reverse("personal:gestion_legajos")).status_code, 200)
        self.assertEqual(self.client.get(reverse("inicio_personal")).status_code, 200)
        self.assertEqual(self.client.get(reverse("personal:catalogos")).status_code, 403)

    def test_subsecretaria_opera_catalogos(self):
        self.usuario_con_rol(SUBSECRETARIA)
        self.assertEqual(self.client.get(reverse("personal:catalogos")).status_code, 200)

    def test_sincronizar_roles_restituye_permisos_de_personal(self):
        grupo = Group.objects.get(name=SECRETARIA)
        grupo.permissions.clear()
        call_command("sincronizar_roles", verbosity=0)
        self.assertIn("change_persona", grupo.permissions.values_list("codename", flat=True))


class AdminParametrosAuditoriaTests(TestCase):
    """M11: editar parámetros desde el admin deja usuario y evento."""

    def test_save_model_completa_usuario_y_registra_evento(self):
        superusuario = User.objects.create_superuser("root", password="x")
        parametros = ParametroSistema.obtener()
        anio_anterior = parametros.ciclo_lectivo
        parametros.ciclo_lectivo = 2031

        peticion = RequestFactory().post("/admin/")
        peticion.user = superusuario
        ParametroSistemaAdmin(ParametroSistema, django_admin.site).save_model(
            peticion, parametros, form=None, change=True
        )

        parametros.refresh_from_db()
        self.assertEqual(parametros.ciclo_lectivo, 2031)
        self.assertEqual(parametros.actualizado_por, superusuario)
        evento = EventoAsistencia.objects.get(accion="PARAMETROS")
        self.assertEqual(evento.usuario, superusuario)
        self.assertIn("admin", evento.motivo)
        self.assertEqual(evento.antes["ciclo_lectivo"], anio_anterior)
        self.assertEqual(evento.despues["ciclo_lectivo"], 2031)


class ExportacionSeguraTests(TestCase):
    """B6: todas las columnas de texto se neutralizan, con todos los prefijos."""

    def test_prefijos_peligrosos(self):
        for valor in ("=1+1", "+1", "-1", "@x", "\tx", "\rx"):
            self.assertEqual(_texto_seguro(valor), "'" + valor)
        self.assertEqual(_texto_seguro("normal"), "normal")
        self.assertEqual(_texto_seguro(None), "")

    def test_codigo_articulo_y_situacion_tambien_se_neutralizan(self):
        fila = FilaConsulta(
            origen="Licencia", pk=1, dni="1", docente="X", cargo="C", carrera="K",
            materia="M", codigo="=A1", articulo="+B2", tipo="T", sit_rev="@TIT",
            desde=date(2026, 1, 1), hasta=None, instrumento="-", justifica="Sí",
        )
        salida = next(filas_consulta([fila]))
        self.assertEqual(salida[6], "'=A1")
        self.assertEqual(salida[7], "'+B2")
        self.assertEqual(salida[9], "'@TIT")
        self.assertEqual(salida[12], "'-")


class OrdenConsultaCombinadaTests(TestCase):
    """B5: el orden es el mismo en toda la paginación, también con empates de fecha."""

    def setUp(self):
        ConsultaUnificadaTests.setUp(self)

    def test_cortes_consecutivos_reconstruyen_el_orden_completo(self):
        inasistencia = MarcaAsistencia.objects.get(codigo="I")
        # Varias ausencias el mismo día que la licencia l2 (empate de fecha entre fuentes).
        for designacion in (self.d_acosta, self.d_benitez):
            for dia in (10, 10, 11):
                RegistroAsistencia.objects.get_or_create(
                    designacion=designacion, fecha=date(2026, 8, dia), marca=inasistencia,
                    defaults={"horas_inasistidas": 1, "estado_justificacion": "INJUSTIFICADA"},
                )
        consulta = buscar_consulta()
        completo = [(f.origen, f.pk) for f in consulta]
        por_paginas = []
        for inicio in range(0, len(consulta), 2):
            por_paginas += [(f.origen, f.pk) for f in consulta[inicio:inicio + 2]]
        self.assertEqual(por_paginas, completo)
        self.assertEqual(len(set(completo)), len(completo))

    def test_empate_de_fecha_entre_fuentes_pone_primero_la_licencia(self):
        inasistencia = MarcaAsistencia.objects.get(codigo="I")
        RegistroAsistencia.objects.create(
            designacion=self.d_acosta, fecha=self.l2.desde, marca=inasistencia,
            horas_inasistidas=1, estado_justificacion="INJUSTIFICADA",
        )
        filas = list(buscar_consulta())
        mismas_fechas = [f.origen for f in filas if f.desde == self.l2.desde]
        self.assertEqual(mismas_fechas, ["Licencia", "Ausencia"])
