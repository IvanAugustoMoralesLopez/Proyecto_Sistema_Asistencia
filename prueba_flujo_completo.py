"""
PRUEBA AUTOMATIZADA DEL FLUJO COMPLETO — archivo TEMPORAL (no subir al repo).

Recorre el sistema como lo haría una persona: abre cada pantalla, lee el
formulario que muestra, lo completa y lo envía, y revisa lo que contesta el
sistema. Empieza con la base vacía y carga todo por las pantallas: catálogos,
legajos, designaciones, asistencia, pendientes, licencias, planilla mensual,
cierres, reportes y usuarios.

Uso (desde la carpeta del proyecto, con MariaDB levantada):

    python prueba_flujo_completo.py              # recorre todo y muestra el resumen
    python prueba_flujo_completo.py --detener    # corta en la primera falla

Trabaja sobre una base de prueba aparte (test_<tu base>) que se crea al empezar
y se borra al terminar: tus datos no se tocan. No prueba el JavaScript de las
pantallas (eso necesita un navegador); sí todo lo que pasa en el servidor.
"""
import os
import sys
import traceback
from datetime import timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.auth.models import Group  # noqa: E402
from django.contrib.messages import get_messages  # noqa: E402
from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.runner import DiscoverRunner  # noqa: E402
from django.urls import reverse  # noqa: E402
from django.utils import timezone  # noqa: E402

DETENER = "--detener" in sys.argv
CLAVE = "Flujo2026!"


def falla(mensaje):
    raise AssertionError(mensaje)


def exigir(condicion, mensaje):
    if not condicion:
        falla(mensaje)


# ───────────────────────── lectura de formularios ─────────────────────────
class _LectorHTML(HTMLParser):
    """Junta los formularios de la página con sus campos, como un navegador."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.formularios = []
        self._form = self._select = self._opcion = self._texto = None

    def handle_starttag(self, tag, attrs):
        a = {k: (v if v is not None else "") for k, v in attrs}
        if tag == "form":
            self._form = {"attrs": a, "campos": []}
            self.formularios.append(self._form)
            return
        if self._form is None:
            return
        deshabilitado = "disabled" in a
        if tag == "input":
            self._form["campos"].append({
                "tag": "input", "name": a.get("name"), "type": (a.get("type") or "text").lower(),
                "value": a.get("value", ""), "checked": "checked" in a, "disabled": deshabilitado,
            })
        elif tag == "button" and a.get("name"):
            self._form["campos"].append({
                "tag": "button", "name": a.get("name"), "type": "boton",
                "value": a.get("value", ""), "disabled": deshabilitado,
            })
        elif tag == "select":
            self._select = {"tag": "select", "name": a.get("name"), "multiple": "multiple" in a,
                            "options": [], "disabled": deshabilitado}
            self._form["campos"].append(self._select)
        elif tag == "option" and self._select is not None:
            self._opcion = {"value": a.get("value"), "selected": "selected" in a,
                            "disabled": deshabilitado, "texto": ""}
            self._select["options"].append(self._opcion)
        elif tag == "textarea":
            self._texto = {"tag": "textarea", "name": a.get("name"), "value": "", "disabled": deshabilitado}
            self._form["campos"].append(self._texto)

    def handle_data(self, data):
        if self._texto is not None:
            self._texto["value"] += data
        if self._opcion is not None:
            self._opcion["texto"] += data

    def handle_endtag(self, tag):
        if tag == "form":
            self._form = None
        elif tag == "select":
            self._select = None
            self._cerrar_opcion()
        elif tag == "option":
            self._cerrar_opcion()
        elif tag == "textarea":
            self._texto = None

    def _cerrar_opcion(self):
        if self._opcion is not None:
            self._opcion["texto"] = " ".join(self._opcion["texto"].split())
            if self._opcion["value"] is None:
                self._opcion["value"] = self._opcion["texto"]
            self._opcion = None


class Opcion:
    """Elige la opción de un desplegable por el texto que se ve en pantalla."""

    def __init__(self, texto):
        self.texto = texto


class Formulario:
    def __init__(self, datos, url):
        self.attrs = datos["attrs"]
        self.campos = datos["campos"]
        self.url = url
        self.accion = None

    def deshabilitado(self, nombre):
        return any(c.get("name") == nombre and c.get("disabled") for c in self.campos)

    def nombres(self):
        return {c["name"] for c in self.campos if c.get("name")}

    def opciones(self, nombre):
        for c in self.campos:
            if c.get("name") == nombre and c["tag"] == "select":
                return [(o["value"], o["texto"]) for o in c["options"]]
        return [(c["value"], c["value"]) for c in self.campos
                if c.get("name") == nombre and c.get("type") in ("checkbox", "radio")]

    def _resolver(self, nombre, valor):
        if isinstance(valor, Opcion):
            for v, texto in self.opciones(nombre):
                if valor.texto.lower() in texto.lower():
                    return v
            falla(f"el campo «{nombre}» no ofrece la opción «{valor.texto}» "
                  f"(ofrece: {[t for _, t in self.opciones(nombre)][:12]})")
        if isinstance(valor, (list, tuple)):
            return [self._resolver(nombre, v) for v in valor]
        return valor

    def datos(self, cambios=None):
        datos = {}

        def agregar(nombre, valor):
            if nombre in datos:
                previo = datos[nombre]
                datos[nombre] = (previo if isinstance(previo, list) else [previo]) + [valor]
            else:
                datos[nombre] = valor

        for c in self.campos:
            nombre = c.get("name")
            if not nombre or c.get("disabled") or c["tag"] == "button":
                continue
            if c["tag"] == "input":
                if c["type"] in ("submit", "button", "reset", "file", "image"):
                    continue
                if c["type"] in ("checkbox", "radio"):
                    if c["checked"]:
                        agregar(nombre, c["value"] or "on")
                    continue
                agregar(nombre, c["value"])
            elif c["tag"] == "textarea":
                agregar(nombre, c["value"].lstrip("\n"))
            elif c["tag"] == "select":
                elegidas = [o for o in c["options"] if o["selected"] and not o["disabled"]]
                if not elegidas and not c["multiple"] and c["options"]:
                    elegidas = [c["options"][0]]
                for o in elegidas:
                    agregar(nombre, o["value"])
        # Como en el navegador: un botón con nombre solo viaja si es el que se
        # aprieta (el de la acción con que se eligió el formulario).
        if self.accion is not None:
            datos["accion"] = self.accion
        for nombre, valor in (cambios or {}).items():
            if valor is None or valor is False:
                datos.pop(nombre, None)
            elif valor is True:
                datos[nombre] = "on"
            else:
                datos[nombre] = self._resolver(nombre, valor)
        return datos


def formularios(respuesta):
    lector = _LectorHTML()
    lector.feed(respuesta.content.decode("utf-8", errors="replace"))
    url = respuesta.wsgi_request.get_full_path()
    return [Formulario(f, url) for f in lector.formularios]


def formulario(respuesta, *, con=(), accion=None, metodo=None):
    """El primer formulario de la página que tenga esos campos (y esa acción)."""
    for f in formularios(respuesta):
        if not set(con) <= f.nombres():
            continue
        if accion is not None and accion not in {
            c.get("value") for c in f.campos if c.get("name") == "accion"
        }:
            continue
        if metodo and (f.attrs.get("method") or "get").lower() != metodo:
            continue
        f.accion = accion
        return f
    falla(f"la pantalla {respuesta.wsgi_request.get_full_path()} no tiene un formulario con "
          f"{list(con)}{' y acción ' + accion if accion else ''}")


def contiene(respuesta, *textos):
    contenido = respuesta.content.decode("utf-8", errors="replace")
    faltan = [t for t in textos if t not in contenido]
    exigir(not faltan, f"la pantalla no muestra {faltan}")


def dia_habil_anterior(fecha):
    fecha -= timedelta(days=1)
    while fecha.weekday() >= 5:
        fecha -= timedelta(days=1)
    return fecha


def ddmmaaaa(fecha):
    return fecha.strftime("%d/%m/%Y")


# ───────────────────────── recorrido y reporte ─────────────────────────
class Recorrido:
    def __init__(self):
        self.ok = 0
        self.fallas = []
        self.seccion = ""
        self.cliente = Client()

    def titulo(self, texto):
        self.seccion = texto
        print(f"\n=== {texto} ===")

    def paso(self, descripcion, funcion):
        try:
            detalle = funcion()
        except Exception as exc:  # noqa: BLE001 — se informa y se sigue
            mensaje = f"{type(exc).__name__}: {exc}"
            if not isinstance(exc, AssertionError):
                mensaje += "\n" + "".join(traceback.format_exc().splitlines(True)[-6:])
            self.fallas.append((self.seccion, descripcion, mensaje))
            print(f"  [FALLA] {descripcion}\n          {mensaje.strip()}")
            if DETENER:
                raise SystemExit(1)
            return None
        self.ok += 1
        texto = detalle if isinstance(detalle, str) and detalle else ""
        print(f"  [OK]    {descripcion}" + (f" — {texto}" if texto else ""))
        return detalle

    def entrar(self, usuario):
        # Cerrar la sesión anterior libera su lugar de carga (el sistema
        # admite tres personas cargando a la vez).
        self.cliente.post(reverse("logout"))
        self.cliente = Client()
        self.cliente.force_login(usuario)

    def abrir(self, url, datos=None, esperado=200):
        respuesta = self.cliente.get(url, datos or {})
        exigir(respuesta.status_code == esperado,
               f"GET {url} devolvió {respuesta.status_code} (se esperaba {esperado})")
        return respuesta

    def enviar(self, form, cambios=None, archivos=None):
        datos = form.datos(cambios)
        datos.update(archivos or {})
        destino = urljoin(form.url, form.attrs.get("action") or form.url)
        if (form.attrs.get("method") or "get").lower() == "post":
            return self.cliente.post(destino, datos)
        return self.cliente.get(destino, datos)

    def post(self, url, datos=None):
        return self.cliente.post(url, datos or {})

    @staticmethod
    def mensajes(respuesta):
        return [str(m) for m in get_messages(respuesta.wsgi_request)]

    @staticmethod
    def errores(respuesta):
        errores = []
        for contexto in (respuesta.context or []):
            for valor in getattr(contexto, "dicts", [contexto]):
                if not isinstance(valor, dict):
                    continue
                for v in valor.values():
                    if hasattr(v, "errors") and getattr(v, "is_bound", False) and v.errors:
                        errores.append(str(v.errors.as_text()))
        return " | ".join(dict.fromkeys(errores))

    @staticmethod
    def errores_en_pantalla(respuesta):
        import re
        html = respuesta.content.decode("utf-8", errors="replace")
        textos = re.findall(r'class="[^"]*(?:invalid-feedback|text-danger|is-invalid|error)[^"]*"[^>]*>\s*([^<]{3,200})', html)
        return [" ".join(t.split()) for t in textos if t.strip()][:5]

    def debe_guardar(self, respuesta, texto=None):
        mensajes = self.mensajes(respuesta)
        exigir(respuesta.status_code in (301, 302),
               f"no guardó (código {respuesta.status_code}). Errores: {self.errores(respuesta) or mensajes}"
               f"{' · En pantalla: ' + str(self.errores_en_pantalla(respuesta)) if respuesta.status_code == 200 else ''}")
        malos = [m for m in mensajes if any(p in m.lower() for p in ("no se pudo", "no tenés", "revise", "error", "no se puede"))]
        exigir(not malos, f"redirigió pero con error: {malos}")
        if texto:
            exigir(any(texto.lower() in m.lower() for m in mensajes),
                   f"no apareció el mensaje «{texto}» (mensajes: {mensajes})")
        return ("; ".join(mensajes)[:140]) or f"→ {respuesta.get('Location', '')}"

    def debe_rechazar(self, respuesta, texto):
        contenido = respuesta.content.decode("utf-8", errors="replace")
        mensajes = self.mensajes(respuesta)
        errores = self.errores(respuesta)
        exigir(texto.lower() in (contenido + " ".join(mensajes) + errores).lower(),
               f"se esperaba el aviso «{texto}». Código {respuesta.status_code}, "
               f"mensajes {mensajes}, errores {errores or '—'}")
        return f"rechazado ({texto})"

    def debe_avisar(self, respuesta, texto):
        mensajes = self.mensajes(respuesta)
        exigir(any(texto.lower() in m.lower() for m in mensajes),
               f"se esperaba el mensaje «{texto}» (mensajes: {mensajes})")
        return f"avisa: {texto}"


# ───────────────────────── el flujo ─────────────────────────
def flujo(r):
    from asistencias.models import CierreMensual, DiaNoLaborable, MarcaAsistencia, RegistroAsistencia
    from asistencias.services.pendientes import pendientes as listar_pendientes
    from licencias.models import LicenciaArticulo, LicenciaOtorgada
    from personal.models import (
        Cargo, Carrera, Designacion, EspacioCurricular, ImportacionPersonalError, Persona,
        TipoInstrumentoLegal,
    )

    U = get_user_model()
    hoy = timezone.localdate()
    lunes = hoy - timedelta(days=hoy.weekday() + 7)      # lunes de la semana pasada
    martes, miercoles, jueves, viernes = (lunes + timedelta(days=i) for i in range(1, 5))
    ayer_habil = dia_habil_anterior(hoy)
    desde_designacion = lunes - timedelta(days=120)
    futuro = hoy + timedelta(days=40)
    while futuro.weekday() >= 5:
        futuro += timedelta(days=1)
    marca = {m.codigo: m.pk for m in MarcaAsistencia.objects.all()}
    print(f"Hoy {ddmmaaaa(hoy)} · semana de prueba {ddmmaaaa(lunes)} a {ddmmaaaa(viernes)} · "
          f"día hábil anterior a hoy {ddmmaaaa(ayer_habil)}")

    # ───── 0. Base ─────
    r.titulo("0. Base de prueba y comandos de carga")

    def base():
        exigir(set(Cargo.objects.values_list("codigo", flat=True)) >= {"150", "155", "165", "166"}, "faltan cargos")
        exigir(set(marca) >= {"PR", "I", "P", "LIC", "LT"}, f"faltan marcas: {set(marca)}")
        exigir(Group.objects.filter(name__in=["Bedelía", "Secretaría", "Subsecretaría"]).count() == 3, "faltan roles")
        return "cargos 150/155/165/166, marcas y 3 roles"
    r.paso("Las migraciones dejaron cargos, marcas y roles", base)
    r.paso("Comando cargar_nomenclador", lambda: (
        call_command("cargar_nomenclador", verbosity=0), f"{LicenciaArticulo.objects.count()} artículos")[1])
    r.paso("Comando sincronizar_roles", lambda: call_command("sincronizar_roles", verbosity=0))

    bedelia = U.objects.create_user("flujo.bedelia", password=CLAVE, first_name="Flujo", last_name="Bedelía")
    bedelia.groups.add(Group.objects.get(name="Bedelía"))

    # ───── 1. Acceso ─────
    r.titulo("1. Acceso y sesión")
    anonimo = Client()

    def sin_sesion():
        resp = anonimo.get(reverse("asistencia:registro_diario"))
        exigir(resp.status_code == 302 and "/accounts/login/" in resp["Location"], f"código {resp.status_code}")
        return f"→ {resp['Location']}"
    r.paso("Sin sesión, Asistencia del día manda al login", sin_sesion)
    r.paso("Pantalla de login", lambda: contiene(anonimo.get(reverse("login")), "Iniciar sesión"))

    def login_malo():
        resp = anonimo.post(reverse("login"), {"username": "flujo.bedelia", "password": "mala"})
        exigir(resp.status_code == 200 and not resp.wsgi_request.user.is_authenticated, "entró con clave mala")
        return "no entra"
    r.paso("Login con contraseña incorrecta", login_malo)

    def login_bueno():
        resp = anonimo.post(reverse("login") + "?next=/asistencia/", {"username": "flujo.bedelia", "password": CLAVE})
        exigir(resp.status_code == 302 and resp["Location"] == "/asistencia/", f"código {resp.status_code}")
        return "entra y vuelve a /asistencia/"
    r.paso("Login correcto con usuario Bedelía", login_bueno)
    r.paso("El menú muestra todas las secciones", lambda: contiene(
        anonimo.get(reverse("inicio_personal")), "Designaciones", "Nueva designación", "Catálogos",
        "Cargar Asistencia", "Historial", "Recepción de formularios", "Cierres", "Calendario escolar",
        "Pendientes", "Nueva licencia", "Licencias otorgadas", "Planilla mensual", "Consultas", "Alertas",
        "Bitácora", "Usuarios y roles", "Parámetros"))

    def cambiar_clave():
        f = formulario(anonimo.get(reverse("password_change")), con=("old_password", "new_password1"))
        resp = anonimo.post(reverse("password_change"), f.datos({
            "old_password": CLAVE, "new_password1": "OtraClave2026!", "new_password2": "OtraClave2026!"}))
        exigir(resp.status_code == 302, f"código {resp.status_code}")
        exigir(anonimo.get(reverse("password_change_done")).status_code == 200, "no abre la confirmación")
        bedelia.set_password(CLAVE)
        bedelia.save()
        return "cambiada y restaurada"
    r.paso("Cambiar la contraseña", cambiar_clave)

    def recuperar():
        exigir(anonimo.get(reverse("password_reset")).status_code == 200, "no abre")
        resp = anonimo.post(reverse("password_reset"), {"email": "nadie@ejemplo.test"})
        exigir(resp.status_code == 302, f"código {resp.status_code}")
        return "formulario y confirmación"
    r.paso("Recuperar contraseña por correo", recuperar)
    r.paso("/pantallas/personal/ redirige al inicio", lambda: exigir(
        anonimo.get("/pantallas/personal/").get("Location") == reverse("inicio_personal"), "no redirige"))
    r.paso("Dirección inexistente devuelve 404", lambda: exigir(anonimo.get("/no-existe/").status_code == 404, "no es 404"))

    def salir():
        resp = anonimo.post(reverse("logout"))
        exigir(resp.status_code in (200, 302), f"código {resp.status_code}")
        exigir(anonimo.get(reverse("asistencia:registro_diario")).status_code == 302, "sigue con sesión")
        return "sesión cerrada"
    r.paso("Cerrar sesión", salir)

    r.entrar(bedelia)

    # ───── 2. Parámetros ─────
    r.titulo("2. Parámetros del sistema")
    url_param = reverse("reportes:parametros")
    r.paso("Ciclo lectivo vacío se rechaza", lambda: r.debe_rechazar(
        r.enviar(formulario(r.abrir(url_param), con=("ciclo_lectivo",)), {"ciclo_lectivo": ""}), "obligatorio"))
    r.paso("Guardar parámetros con límite anual 10", lambda: r.debe_guardar(r.enviar(
        formulario(r.abrir(url_param), con=("ciclo_lectivo",)),
        {"codigo_oficina": "1452", "nombre_oficina": "IESETyFP", "ciclo_lectivo": str(hoy.year),
         "limite_inasistencias_anual": "10"})))

    # ───── 3. Usuarios ─────
    r.titulo("3. Usuarios y roles")
    url_usuarios = reverse("reportes:usuarios")
    r.paso("Listado, búsqueda y filtro por rol", lambda: (
        contiene(r.abrir(url_usuarios), "flujo.bedelia"), r.abrir(url_usuarios, {"q": "flujo", "rol": "Bedelía"}),
        r.abrir(url_usuarios, {"q": "zzz"}))[0])

    def form_usuario(**cambios):
        f = formulario(r.abrir(reverse("reportes:usuario_crear")), con=("username", "password1"))
        base = {"username": "flujo.secretaria", "first_name": "Flujo", "last_name": "Secretaría",
                "email": "secretaria@ejemplo.test", "is_active": True, "rol": Opcion("Secretar"),
                "password1": CLAVE, "password2": CLAVE}
        base.update(cambios)
        return r.enviar(f, base)
    r.paso("Nuevo usuario con contraseñas distintas se rechaza", lambda: r.debe_rechazar(
        form_usuario(password2="Distinta2026!"), "contraseña"))
    r.paso("Nuevo usuario Secretaría", lambda: r.debe_guardar(form_usuario()))
    secretaria = U.objects.filter(username="flujo.secretaria").first()

    def editar_usuario(**cambios):
        f = formulario(r.abrir(reverse("reportes:usuario_editar", args=[secretaria.pk])), con=("username",))
        return r.enviar(f, cambios)
    r.paso("Editar usuario: pasarlo a Subsecretaría", lambda: r.debe_guardar(editar_usuario(rol=Opcion("Subsecretar"))))

    def desactivar():
        r.debe_guardar(editar_usuario(is_active=False))
        exigir(Client().login(username="flujo.secretaria", password=CLAVE) is False, "un usuario inactivo pudo entrar")
        return "no puede entrar"
    r.paso("Desactivar usuario", desactivar)

    def reactivar():
        r.debe_guardar(editar_usuario(is_active=True, rol=Opcion("Secretar")))
        exigir(Client().login(username="flujo.secretaria", password=CLAVE), "no pudo entrar")
        return "vuelve a entrar como Secretaría"
    r.paso("Reactivar usuario", reactivar)
    if secretaria:
        secretaria.refresh_from_db()
    else:
        secretaria = U.objects.create_user("flujo.secretaria", password=CLAVE)
        secretaria.groups.add(Group.objects.get(name="Secretaría"))

    # ───── 4. Catálogos ─────
    r.titulo("4. Catálogos")
    url_cat = reverse("personal:catalogos")

    def guardar_catalogo(seccion, cambios, editar=None):
        url = f"{url_cat}?seccion={seccion}" + (f"&editar={editar}" if editar else "")
        return r.enviar(formulario(r.abrir(url), accion="guardar"), cambios)

    def eliminar_catalogo(seccion, pk):
        return r.post(f"{url_cat}?seccion={seccion}", {"accion": "eliminar", "objeto_id": pk})

    r.paso("Pestaña Cargos lista 150, 155, 165 y 166", lambda: contiene(
        r.abrir(f"{url_cat}?seccion=cargos"), "Secretaría", "Director de Estudio", "Bedel", "Horas cátedra"))
    r.paso("Cargo con código «HC» se rechaza", lambda: r.debe_rechazar(
        guardar_catalogo("cargos", {"codigo": "HC", "descripcion": "Horas", "activo": True}), "numérico"))
    r.paso("Agregar cargo 170 Preceptor", lambda: r.debe_guardar(
        guardar_catalogo("cargos", {"codigo": "170", "descripcion": "Preceptor", "activo": True})))

    def editar_cargo():
        r.debe_guardar(guardar_catalogo("cargos", {"codigo": "999", "descripcion": "Preceptor editado"}, editar="170"))
        exigir(not Cargo.objects.filter(codigo="999").exists(), "cambió el código")
        exigir(Cargo.objects.get(codigo="170").descripcion == "Preceptor editado", "no guardó la descripción")
        return "código fijo, descripción cambiada"
    r.paso("Editar cargo 170", editar_cargo)
    r.paso("Cargo duplicado (166) se rechaza", lambda: r.debe_rechazar(
        guardar_catalogo("cargos", {"codigo": "166", "descripcion": "Otra", "activo": True}), "ya existe"))

    def baja_cargo():
        r.debe_guardar(eliminar_catalogo("cargos", "170"))
        exigir(not Cargo.objects.get(codigo="170").activo, "sigue activo")
        return "desactivado"
    r.paso("Eliminar cargo 170", baja_cargo)

    for nombre in ("Desarrollo de Software", "Higiene y Seguridad en el Trabajo", "Gestión Administrativa",
                   "Tecnicatura de Prueba"):
        r.paso(f"Agregar carrera «{nombre}»", lambda n=nombre: r.debe_guardar(guardar_catalogo(
            "carreras", {"nombre": n, "plan_estudio": "Plan 2020", "anio_plan": "2020",
                         "activa": True, "plan_vigente": True})))
    carrera = {c.nombre: c.pk for c in Carrera.objects.all()}

    def editar_borrar_carrera():
        pk = carrera["Tecnicatura de Prueba"]
        r.debe_guardar(guardar_catalogo("carreras", {"plan_estudio": "Plan 2024"}, editar=pk))
        r.debe_guardar(eliminar_catalogo("carreras", pk))
        exigir(not Carrera.objects.get(pk=pk).activa, "sigue activa")
        return "editada y desactivada"
    r.paso("Editar y eliminar «Tecnicatura de Prueba»", editar_borrar_carrera)

    SW = carrera.get("Desarrollo de Software")
    HI = carrera.get("Higiene y Seguridad en el Trabajo")
    GE = carrera.get("Gestión Administrativa")
    materias = {"Programación I": [SW], "Contabilidad": [GE], "Legislación Laboral": [HI, GE],
                "Ergonomía": [HI], "Inglés Técnico": [SW, GE]}
    for nombre, carreras in materias.items():
        r.paso(f"Agregar materia «{nombre}» en {len(carreras)} carrera(s)", lambda n=nombre, c=carreras: r.debe_guardar(
            guardar_catalogo("espacios", {"nombre": n, "carreras": [str(x) for x in c], "activo": True})))
    r.paso("Materia sin carreras se rechaza", lambda: r.debe_rechazar(
        guardar_catalogo("espacios", {"nombre": "Sin carrera", "carreras": None, "activo": True}), "obligatorio"))
    def materia_existente():
        r.debe_guardar(guardar_catalogo("espacios", {"nombre": "ingles tecnico", "carreras": [str(HI)], "activo": True}),
                       "ya existía")
        exigir(EspacioCurricular.objects.filter(nombre__iexact="Inglés Técnico").count() == 1, "se duplicó la materia")
        carreras = set(EspacioCurricular.objects.get(nombre="Inglés Técnico").carreras.values_list("pk", flat=True))
        exigir(carreras == {SW, GE, HI}, f"carreras: {carreras}")
        return "no se duplica: se le suma Higiene"
    r.paso("Cargar otra vez «ingles tecnico» le suma la carrera a la existente", materia_existente)
    r.paso("La lista de materias muestra sus carreras", lambda: contiene(
        r.abrir(f"{url_cat}?seccion=espacios"), "Desarrollo de Software ·"))
    materia = {e.nombre: e.pk for e in EspacioCurricular.objects.all()}

    def editar_materia():
        pk = materia["Inglés Técnico"]
        r.debe_rechazar(guardar_catalogo("espacios", {"nombre": "Contabilidad"}, editar=pk), "Ya hay otra materia")
        r.debe_guardar(guardar_catalogo("espacios", {"carreras": [str(SW), str(GE), str(HI)]}, editar=pk))
        exigir(EspacioCurricular.objects.get(pk=pk).carreras.count() == 3, "no quedó en 3 carreras")
        r.debe_guardar(eliminar_catalogo("espacios", pk))
        exigir(not EspacioCurricular.objects.get(pk=pk).activo, "sigue activa")
        return "3 carreras y después desactivada"
    r.paso("Editar «Inglés Técnico» (renombrar a otra existente se rechaza) y eliminarla", editar_materia)

    def instrumento():
        r.debe_guardar(guardar_catalogo("instrumentos", {"nombre": "Decreto", "activo": True}))
        pk = TipoInstrumentoLegal.objects.get(nombre="Decreto").pk
        r.debe_guardar(guardar_catalogo("instrumentos", {"nombre": "Decreto provincial"}, editar=pk))
        r.debe_guardar(eliminar_catalogo("instrumentos", pk))
        exigir(not TipoInstrumentoLegal.objects.get(pk=pk).activo, "sigue activo")
        return "alta, edición y baja"
    r.paso("Instrumento legal «Decreto»", instrumento)

    def tipo_licencia():
        r.debe_guardar(guardar_catalogo("licencias", {
            "cod_licencia": "FLUJO-1", "articulo": "999", "tipo_licencia": "Prueba del flujo",
            "clase": Opcion("Permiso"), "categoria_informe": Opcion("Razones particulares"),
            "sit_rev": Opcion("Titular"), "goce_haberes": "Con goce", "autoridad": "Director",
            "plazo": "1 día", "tope_dias_anual": "5"}))
        articulo = LicenciaArticulo.objects.get(cod_licencia="FLUJO-1")
        r.debe_guardar(guardar_catalogo("licencias", {"plazo": "2 días"}, editar=articulo.pk))
        r.debe_guardar(eliminar_catalogo("licencias", articulo.pk))
        exigir(not LicenciaArticulo.objects.filter(pk=articulo.pk).exists(), "no se borró")
        return "alta, edición y borrado"
    r.paso("Tipo de licencia de prueba", tipo_licencia)

    def catalogo_inexistente():
        r.abrir(f"{url_cat}?seccion=cargos&editar=INEXISTENTE", esperado=302)
        exigir(eliminar_catalogo("cargos", "INEXISTENTE").status_code == 302, "no redirige")
        return "sin error 500"
    r.paso("Catálogo con id inexistente", catalogo_inexistente)

    # ───── 5. Legajos y designaciones ─────
    r.titulo("5. Legajos (Personal) y designaciones")
    url_leg = reverse("personal:gestion_legajos")

    def guardar_persona(**cambios):
        return r.enviar(formulario(r.abrir(url_leg), accion="guardar_persona"), cambios)
    r.paso("Legajo con DNI «ABC123» se rechaza", lambda: r.debe_rechazar(
        guardar_persona(dni="ABC123", apellido_nombre="Inválido, Docente"), "DNI"))
    r.paso("Legajo sin nombre se rechaza", lambda: r.debe_rechazar(
        guardar_persona(dni="99100009", apellido_nombre=""), "nombre y apellido"))
    docentes = {"99100001": "FLUJO, Ana", "99100002": "FLUJO, Bruno", "99100003": "FLUJO, Carla",
                "99100004": "FLUJO, Darío", "99100005": "FLUJO, Elena"}
    for dni, nombre in docentes.items():
        r.paso(f"Alta de legajo {dni} {nombre}", lambda d=dni, n=nombre: r.debe_guardar(guardar_persona(
            dni=d, apellido_nombre=n, sexo=Opcion("Femenino"), fecha_nacimiento="1980-05-10",
            telefono="3794000000", email=f"{d}@ejemplo.test", activa=True)))

    def editar_legajo():
        f = formulario(r.abrir(url_leg, {"dni": "99100001"}), accion="guardar_persona")
        exigir(f.deshabilitado("dni"), "el DNI se puede editar")
        r.debe_guardar(r.enviar(f, {"telefono": "3794111111"}))
        exigir(Persona.objects.get(pk="99100001").telefono == "3794111111", "no guardó el teléfono")
        return "DNI bloqueado, teléfono cambiado"
    r.paso("Editar legajo", editar_legajo)
    r.paso("Buscar legajos por DNI, apellido, cargo y materia", lambda: (
        contiene(r.abrir(url_leg, {"dni": "99100002"}), "FLUJO, Bruno"),
        r.abrir(url_leg, {"dni": "flujo", "cargo": "166"}))[0])
    r.paso("Autocompletar legajos", lambda: exigir(
        len(r.abrir(reverse("personal:legajos_autocompletar"), {"q": "flujo"}).json()["resultados"]) >= 5,
        "no encontró los legajos"))

    def designar(dni, cambios):
        f = formulario(r.abrir(url_leg, {"dni": dni}), accion="guardar_designacion")
        # Las horas cátedra nombradas son las que suma el horario (deben coincidir).
        horas = sum(int(v) for k, v in cambios.items() if k.startswith("horas_"))
        base = {"cargo": "166", "situacion_revista": "TIT", "desde": ddmmaaaa(desde_designacion),
                "hasta": "SIN TERMINO", "norma_tipo": "Resolución", "norma_numero": "100",
                "norma_anio": str(hoy.year), "organismo_emisor": "Ministerio de Educación",
                "anio_curso": "1°", "division_seccion": "A", "turno": "Noche",
                "hs_catedra": str(horas or 4)}
        base.update(cambios)
        return r.enviar(f, base)

    r.paso("Materia de varias carreras sin carrera se rechaza", lambda: r.debe_rechazar(
        designar("99100002", {"espacio_curricular": materia["Legislación Laboral"], "carrera": "", "horas_lun": "2"}),
        "varias carreras"))
    r.paso("Carrera que no tiene la materia se rechaza", lambda: r.debe_rechazar(
        designar("99100002", {"espacio_curricular": materia["Contabilidad"], "carrera": str(SW), "horas_lun": "2"}),
        "no pertenece"))
    r.paso("Fecha inválida «32/13/2026» se rechaza", lambda: r.debe_rechazar(
        designar("99100001", {"espacio_curricular": materia["Programación I"], "desde": "32/13/2026"}), "fecha"))
    r.paso("Hasta anterior a Desde se rechaza", lambda: r.debe_rechazar(designar(
        "99100001", {"espacio_curricular": materia["Programación I"],
                     "hasta": ddmmaaaa(desde_designacion - timedelta(days=5))}), "anterior"))
    r.paso("Horario que no suma las horas nombradas se rechaza", lambda: r.debe_rechazar(designar(
        "99100001", {"espacio_curricular": materia["Programación I"], "horas_lun": "2", "hs_catedra": "5"}),
        "deben coincidir"))
    r.paso("Suplente sin fecha de cese ni SIN TERMINO se rechaza", lambda: r.debe_rechazar(designar(
        "99100003", {"espacio_curricular": materia["Ergonomía"], "situacion_revista": "SUP",
                     "hasta": "", "horas_lun": "2"}), "fecha de cese"))

    altas = [
        ("99100001", "Programación I", {"horas_lun": "3", "horas_mie": "2", "horas_vie": "2"}),
        ("99100002", "Legislación Laboral", {"carrera": str(GE), "situacion_revista": "INT", "horas_lun": "2", "horas_mar": "2"}),
        ("99100002", "Contabilidad", {"horas_lun": "2", "horas_jue": "2"}),
        ("99100004", "Legislación Laboral", {"carrera": str(HI), "horas_mar": "3", "horas_mie": "3"}),
        ("99100005", "Ergonomía", {"desde": "SIN INICIO", "horas_jue": "2"}),
    ]
    for dni, nombre_materia, cambios in altas:
        r.paso(f"Designación de {docentes[dni]} en {nombre_materia}", lambda d=dni, m=nombre_materia, c=cambios: r.debe_guardar(
            designar(d, {"espacio_curricular": materia[m], **c})))

    def carrera_sola():
        d = Designacion.objects.get(persona_id="99100002", espacio_curricular_id=materia["Contabilidad"])
        exigir(d.carrera_id == GE, "no completó la carrera")
        return "Contabilidad → Gestión Administrativa"
    r.paso("La materia de una sola carrera completa la carrera sola", carrera_sola)
    r.paso("SIN INICIO se guarda como tal", lambda: exigir(
        Designacion.objects.get(persona_id="99100005").desde_texto == "SIN INICIO", "no quedó SIN INICIO"))
    d_ana = Designacion.objects.filter(persona_id="99100001").first()
    def suplencia_valida():
        r.debe_guardar(designar(
            "99100003", {"espacio_curricular": materia["Ergonomía"], "situacion_revista": "SUP",
                         "hasta": "SIN TERMINO", "reemplaza": str(d_ana.pk),
                         "horas_lun": "2", "horas_vie": "2"}))
        s = Designacion.objects.get(persona_id="99100003", espacio_curricular_id=materia["Ergonomía"])
        exigir(s.es_suplencia and s.plazo_indeterminado, "Suplente + SIN TERMINO no quedó de plazo indeterminado")
        return "suplencia de plazo indeterminado sin casillas aparte"
    r.paso("Suplencia válida (Carla reemplaza a Ana, SIN TERMINO)", suplencia_valida)
    r.paso("Suplencia que se reemplaza a sí misma se rechaza", lambda: r.debe_rechazar(designar(
        "99100001", {"espacio_curricular": materia["Programación I"], "situacion_revista": "SUP",
                     "hasta": "SIN TERMINO", "reemplaza": str(d_ana.pk), "horas_lun": "2"}), "sí mismo"))

    def editar_en_legajo():
        f = formulario(r.abrir(url_leg, {"dni": "99100001", "designacion": d_ana.pk}), accion="guardar_designacion")
        r.debe_guardar(r.enviar(f, {"turno": "Tarde"}))
        d_ana.refresh_from_db()
        exigir(d_ana.turno == "Tarde", "no guardó el turno")
        exigir(d_ana.historial.filter(accion="MODIFICACION").exists(), "sin historial de modificación")
        return "turno Tarde + historial Modificación"
    r.paso("Editar designación desde el legajo", editar_en_legajo)

    def asistente():
        f = formulario(r.abrir(reverse("personal:nueva_designacion"), {"dni": "99100004"}), con=("persona", "cargo"))
        return r.debe_guardar(r.enviar(f, {
            "persona": "99100004", "cargo": "166", "espacio_curricular": materia["Programación I"],
            "situacion_revista": "INT", "desde": ddmmaaaa(desde_designacion), "hasta": "SIN TERMINO",
            "norma_tipo": "Disposición", "norma_numero": "55", "norma_anio": str(hoy.year),
            "hs_catedra": "2", "horas_vie": "2"}))
    r.paso("Nueva designación con el asistente (Darío, Programación I)", asistente)
    d_baja = Designacion.objects.filter(persona_id="99100004", espacio_curricular_id=materia["Programación I"]).first()

    def editar_y_renovar():
        url = reverse("personal:editar_designacion", args=[d_baja.pk])
        contiene(r.abrir(url, {"renovar": "1"}), "Renovar / extender")
        nuevo = hoy + timedelta(days=200)
        r.debe_guardar(r.enviar(formulario(r.abrir(url), con=("persona", "cargo")), {"hasta": ddmmaaaa(nuevo)}))
        d_baja.refresh_from_db()
        exigir(d_baja.hasta == nuevo, f"hasta quedó en {d_baja.hasta}")
        return "nueva vigencia guardada"
    r.paso("Modificar y Renovar / extender designación", editar_y_renovar)

    def dar_baja():
        r.debe_guardar(r.post(url_leg, {"accion": "dar_baja_designacion", "dni": "99100004", "designacion_id": d_baja.pk}))
        exigir(not Designacion.objects.get(pk=d_baja.pk).activo, "sigue activa")
        return "baja lógica"
    r.paso("Dar de baja una designación", dar_baja)
    r.paso("Listado de designaciones (inicio) con código y carrera", lambda: contiene(
        r.abrir(reverse("inicio_personal"), {"q": "Gestión"}), "166", "FLUJO, Bruno", "Gestión Administrativa"))
    r.paso("Filtro por situación de revista", lambda: contiene(
        r.abrir(reverse("inicio_personal"), {"sit_revista": "INT"}), "FLUJO, Bruno"))
    r.paso("Autocompletar designaciones", lambda: exigir(
        r.abrir(reverse("personal:designaciones_autocompletar"), {"q": "flujo"}).json()["resultados"], "sin resultados"))

    # ───── 6. Importación CSV ─────
    r.titulo("6. Importación CSV de personal")
    r.paso("Descargar plantilla CSV", lambda: contiene(
        r.abrir(reverse("personal:plantilla_importacion_csv")), "dni", "cargo_codigo", "carrera"))
    d = desde_designacion.isoformat()
    csv = ("dni,nombre_apellido,sexo,cargo_codigo,situacion_revista,espacio_curricular,carrera,desde,hasta,horas_lun\n"
           f"99100101,\"CSV, Uno\",F,166,TITULAR,Contabilidad,,{d},SIN TERMINO,2\n"
           f"99100102,\"CSV, Dos\",M,166,INTERINO,Legislación Laboral,Gestión Administrativa,{d},,3\n"
           f"99100103,\"CSV, Tres\",M,HC,TITULAR,Contabilidad,,{d},,2\n"
           f"99100104,\"CSV, Cuatro\",F,166,TITULAR,Legislación Laboral,,{d},,2\n"
           "99100105,\"CSV, Solo Legajo\",F,,,,,,,\n").encode("utf-8")

    def subir(nombre, contenido):
        f = formulario(r.abrir(url_leg), accion="importar_csv")
        return r.enviar(f, archivos={"archivo": SimpleUploadedFile(nombre, contenido, content_type="text/csv")})
    r.paso("Archivo .txt se rechaza", lambda: r.debe_rechazar(subir("personas.txt", csv), ".csv"))

    def previa_y_cancelar():
        pagina = subir("personas.csv", csv)
        contiene(pagina, "Revise antes de confirmar")
        r.enviar(formulario(pagina, accion="cancelar_csv"))
        exigir(not Persona.objects.filter(pk="99100101").exists(), "importó al cancelar")
        return "vista previa y cancelado sin importar"
    r.paso("Vista previa y Cancelar", previa_y_cancelar)

    def confirmar():
        pagina = subir("personas.csv", csv)
        r.enviar(formulario(pagina, accion="confirmar_csv"))
        exigir(Persona.objects.filter(pk__in=["99100101", "99100102", "99100105"]).count() == 3, "no importó las 3 filas buenas")
        motivos = list(ImportacionPersonalError.objects.order_by("-pk").values_list("motivo_error", flat=True)[:2])
        exigir(any("HC" in m for m in motivos) and any("más de una carrera" in m for m in motivos), f"rechazos: {motivos}")
        return "3 importadas; rechazadas: cargo HC y materia sin carrera"
    r.paso("Confirmar e importar", confirmar)

    def duplicado():
        antes = ImportacionPersonalError.objects.count()
        r.enviar(formulario(subir("personas.csv", csv), accion="confirmar_csv"))
        nuevos = list(ImportacionPersonalError.objects.filter(pk__gt=0).order_by("-pk")
                      .values_list("motivo_error", flat=True)[:ImportacionPersonalError.objects.count() - antes])
        exigir(sum("duplica" in m for m in nuevos) == 2, f"rechazos: {nuevos}")
        return "las 2 designaciones repetidas se rechazan"
    r.paso("Importar el mismo CSV otra vez", duplicado)

    def punto_y_coma():
        pagina = subir("excel.csv", "dni;nombre_apellido\n99100106;\"CSV, Excel\"\n".encode("utf-8"))
        r.enviar(formulario(pagina, accion="confirmar_csv"))
        exigir(Persona.objects.filter(pk="99100106").exists(), "no se importó")
        return "leído con separador ;"
    r.paso("CSV separado por punto y coma (Excel)", punto_y_coma)

    # ───── 7. Calendario ─────
    r.titulo("7. Calendario escolar")
    r.paso("Listado del calendario", lambda: r.abrir(reverse("asistencia:lista_calendario")) and None)

    def nuevo_dia(fecha):
        f = formulario(r.abrir(reverse("asistencia:crear_dia_no_laborable")), con=("fecha", "tipo"))
        return r.enviar(f, {"fecha": fecha.isoformat(), "tipo": "FERIADO", "descripcion": "Feriado de prueba"})
    r.paso("Nuevo feriado", lambda: r.debe_guardar(nuevo_dia(futuro)))
    r.paso("Feriado repetido se rechaza", lambda: r.debe_rechazar(nuevo_dia(futuro), "Ya hay un día"))

    def editar_borrar_dia():
        dia = DiaNoLaborable.objects.get(fecha=futuro)
        f = formulario(r.abrir(reverse("asistencia:editar_dia_no_laborable", args=[dia.pk])), con=("fecha", "tipo"))
        r.debe_guardar(r.enviar(f, {"tipo": "ASUETO", "descripcion": "Asueto de prueba"}))
        exigir(DiaNoLaborable.objects.get(pk=dia.pk).tipo == "ASUETO", "no cambió el tipo")
        r.debe_guardar(r.post(reverse("asistencia:eliminar_dia_no_laborable", args=[dia.pk])))
        exigir(not DiaNoLaborable.objects.filter(pk=dia.pk).exists(), "no se borró")
        return "editado y eliminado"
    r.paso("Editar (pasa a Asueto) y eliminar el día", editar_borrar_dia)

    def masivo():
        f = formulario(r.abrir(reverse("asistencia:cargar_masivo")), con=("fechas", "tipo"))
        fechas = [futuro + timedelta(days=x) for x in (0, 1, 7)]
        r.debe_guardar(r.enviar(f, {"fechas": "\n".join(x.isoformat() for x in fechas), "tipo": "INHABIL"}))
        exigir(DiaNoLaborable.objects.filter(fecha__in=fechas).count() == 3, "no se crearon los 3 días")
        return "3 días inhábiles"
    r.paso("Carga masiva de días inhábiles", masivo)

    def copiar_anio():
        f = formulario(r.abrir(reverse("asistencia:copiar_calendario")), con=("anio_origen", "anio_destino"))
        r.debe_guardar(r.enviar(f, {"anio_origen": str(futuro.year), "anio_destino": str(futuro.year + 1)}))
        exigir(DiaNoLaborable.objects.filter(fecha__year=futuro.year + 1).exists(), "no copió")
        return f"{futuro.year} → {futuro.year + 1}"
    r.paso("Copiar el calendario al año siguiente", copiar_anio)

    # ───── 8. Planilla del día ─────
    r.titulo("8. Cargar asistencia (planilla del día)")
    url_pl = reverse("asistencia:planilla_rapida")

    def planilla(fecha, alcance="clase"):
        return r.abrir(url_pl, {"fecha": fecha.isoformat(), "alcance": alcance})

    def form_planilla(fecha, alcance="clase", respuesta=None):
        """El formulario de la planilla (el que tiene las marcas por docente)."""
        for f in formularios(respuesta or planilla(fecha, alcance)):
            if (f.attrs.get("method") or "").lower() == "post" and any(
                    n.startswith("agente-marca-") for n in f.nombres()):
                return f
        falla(f"la planilla del {ddmmaaaa(fecha)} no tiene docentes para marcar")

    def registros_del(fecha):
        return [f"{x.designacion.persona_id}/{x.designacion.espacio_curricular}/{x.marca.codigo}/{x.horas_inasistidas}"
                for x in RegistroAsistencia.objects.filter(fecha=fecha).select_related("designacion", "marca")]

    r.paso(f"Abrir la planilla del lunes {ddmmaaaa(lunes)} (docentes con clase)", lambda: contiene(
        planilla(lunes), "FLUJO, Ana", "FLUJO, Bruno", "Programación I", "Contabilidad"))
    r.paso("Día inhábil del calendario: la planilla avisa sin bloquear", lambda: contiene(planilla(futuro), "nhábil"))
    r.paso("Copiar el día anterior sin nada cargado avisa", lambda: exigir(
        "No hay nada cargado" in r.enviar(form_planilla(lunes), {"accion": "copiar"}).content.decode(),
        "no avisó que no había nada para copiar"))
    r.paso("Inasistencia sin horas en un docente sin clase ese día se rechaza (Elena, «todos»)", lambda: r.debe_rechazar(
        r.enviar(form_planilla(lunes, "todos"), {"agente-marca-99100005": marca["I"], "agente-horas-99100005": "0"}),
        "no tiene horario cargado"))
    r.paso("Ese intento no guardó nada", lambda: exigir(not registros_del(lunes), f"guardó {registros_del(lunes)}"))

    def guardar_lunes():
        r.debe_guardar(r.enviar(form_planilla(lunes), {
            "agente-marca-99100001": marca["PR"],
            "agente-marca-99100002": marca["I"], "agente-horas-99100002": "",
            "agente-obs-99100002": "Avisó por teléfono",
            "agente-marca-99100003": marca["LIC"]}))
        cargados = registros_del(lunes)
        # Los que no se tocaron quedan con la propuesta del sistema: «Asistió».
        exigir(len(cargados) == 6, f"se esperaban 6 registros (Ana, Bruno ×2, Carla y los 2 del CSV) y hay {cargados}")
        exigir(all(x.endswith("/PR/0.00") for x in cargados if x.startswith(("99100101", "99100102"))),
               f"los no tocados no quedaron con «Asistió»: {cargados}")
        horas = sum(x.horas_inasistidas for x in RegistroAsistencia.objects.filter(fecha=lunes, designacion__persona_id="99100002"))
        exigir(horas == 4, f"Bruno debería sumar 4 hs del horario y suma {horas}")
        return "PR Ana · I Bruno (2 materias, 4 hs del horario) · LIC Carla · los no tocados con «Asistió» propuesto"
    r.paso("Guardar la planilla del lunes", guardar_lunes)

    def copiar_martes():
        resp = r.enviar(form_planilla(martes), {"accion": "copiar"})
        exigir("Se trajo lo cargado" in resp.content.decode(), f"no copió: {r.mensajes(resp)}")
        r.debe_guardar(r.enviar(form_planilla(martes, respuesta=resp), {
            "agente-marca-99100004": marca["LT"], "agente-marca-99100002": marca["P"], "agente-horas-99100002": "2"}))
        return f"martes: {registros_del(martes)}"
    r.paso("Martes: copiar lo del día anterior y guardar (P Bruno, LT Darío)", copiar_martes)

    def todos_presentes(fecha):
        # Elena queda sin marcar: su falta se carga como «docente suelto».
        f = form_planilla(fecha)
        marcas = {k: marca["PR"] for k in f.nombres() if k.startswith("agente-marca-") and k != "agente-marca-99100005"}
        return r.debe_guardar(r.enviar(f, marcas))
    for fecha in (miercoles, jueves, viernes):
        r.paso(f"Planilla del {ddmmaaaa(fecha)} con todos presentes", lambda f=fecha: todos_presentes(f))

    def liberar_renovar():
        planilla(viernes)
        resp = r.post(reverse("asistencia:renovar_edicion"))
        exigir(resp.status_code in (200, 204, 302), f"renovar devolvió {resp.status_code}")
        resp = r.post(reverse("asistencia:liberar_edicion"), {"next": url_pl})
        exigir(resp.status_code in (200, 302), f"liberar devolvió {resp.status_code}")
        return "renovado y liberado"
    r.paso("Renovar y liberar el lugar de carga", liberar_renovar)

    # ───── 9. Asistencia del día, docente suelto, historial ─────
    r.titulo("9. Asistencia del día, docente suelto, historial y validación")
    url_dia = reverse("asistencia:registro_diario")
    url_hist = reverse("asistencia:historial")
    r.paso("Asistencia del día del lunes", lambda: contiene(r.abrir(url_dia, {"fecha": lunes.isoformat()}), "FLUJO, Bruno"))

    def ficha():
        d_leg = Designacion.objects.get(persona_id="99100002", espacio_curricular_id=materia["Legislación Laboral"])
        datos = r.abrir(reverse("asistencia:datos_designacion"),
                        {"designacion": d_leg.pk, "fecha": lunes.isoformat()}).json()
        exigir(datos["designacion"]["carrera"] == "Gestión Administrativa", f"ficha: {datos['designacion']}")
        exigir(datos["tiene_clase"], "el lunes debería tener clase")
        return f"{datos['designacion']['materia']} — {datos['designacion']['carrera']}, {datos['horas_dia']} hs"
    r.paso("Ficha de la designación para el alta individual", ficha)

    d_elena = Designacion.objects.filter(persona_id="99100005").first()

    def suelto(fecha, codigo, horas):
        f = formulario(r.abrir(reverse("asistencia:crear_asistencia")), con=("designacion", "fecha", "marca"))
        return r.enviar(f, {"designacion": str(d_elena.pk), "fecha": fecha.isoformat(), "marca": str(marca[codigo]),
                            "horas_inasistidas": horas, "observaciones": "Carga individual"})
    r.paso(f"Docente suelto: Elena falta el {ddmmaaaa(ayer_habil)}", lambda: r.debe_guardar(suelto(ayer_habil, "I", "2")))
    r.paso("El mismo docente y día otra vez se rechaza", lambda: r.debe_rechazar(suelto(ayer_habil, "PR", "0"), "ya"))
    reg_bruno = RegistroAsistencia.objects.filter(fecha=lunes, designacion__persona_id="99100002").order_by("pk")

    def corregir_agente():
        url = reverse("asistencia:editar_asistencia", args=[reg_bruno.first().pk])
        f = formulario(r.abrir(url), con=("marca",))
        exigir("aplicar_al_agente" in f.nombres(), "no ofrece aplicar el cambio a las otras materias")
        r.debe_guardar(r.enviar(f, {"marca": str(marca["P"]), "aplicar_al_agente": "1"}))
        exigir({x.marca.codigo for x in reg_bruno.all()} == {"P"}, "la otra materia no pasó a Permiso")
        r.debe_guardar(r.enviar(formulario(r.abrir(url), con=("marca",)), {"marca": str(marca["I"]), "aplicar_al_agente": "1"}))
        exigir({x.marca.codigo for x in reg_bruno.all()} == {"I"}, "la otra materia no volvió a Inasistencia")
        return "I → P → I en las 2 materias a la vez"
    r.paso("Corregir aplicando el cambio a las otras materias", corregir_agente)
    r.paso("Detalle del registro con historial de cambios", lambda: contiene(
        r.abrir(reverse("asistencia:detalle_asistencia", args=[reg_bruno.first().pk])), "Historial de cambios"))
    filtros_hist = [{}, {"dni": "99100002"}, {"apellido_nombre": "flujo"},
                    {"desde": lunes.isoformat(), "hasta": viernes.isoformat()}, {"marca": marca["I"]},
                    {"espacio_curricular": materia["Contabilidad"]}, {"estado_registro": "BORRADOR"},
                    {"estado_justificacion": "INJUSTIFICADA"}]
    r.paso("Historial con cada filtro", lambda: (
        [r.abrir(url_hist, p) for p in filtros_hist], f"{len(filtros_hist)} búsquedas")[1])
    r.paso("Bajar el historial a Excel (CSV)", lambda: (
        lambda resp: (exigir("csv" in resp["Content-Type"], resp["Content-Type"]), resp["Content-Type"])[1])(
        r.abrir(reverse("asistencia:exportar_csv"), {"desde": lunes.isoformat()})))

    r.entrar(secretaria)

    def validar_uno():
        reg = reg_bruno.first()
        r.post(reverse("asistencia:validar_registro", args=[reg.pk]), {"next": url_hist})
        exigir(RegistroAsistencia.objects.get(pk=reg.pk).estado_registro == "VALIDADO", "no quedó validado")
        return "Revisado por Secretaría"
    r.paso("Secretaría valida un registro", validar_uno)

    def corregir_validado():
        reg = reg_bruno.first()
        url = reverse("asistencia:editar_asistencia", args=[reg.pk])
        r.debe_rechazar(r.enviar(formulario(r.abrir(url), con=("marca",)),
                                 {"observaciones": "x", "motivo": "", "aplicar_al_agente": None}), "motivo")
        r.debe_guardar(r.enviar(formulario(r.abrir(url), con=("marca",)),
                                {"observaciones": "x", "motivo": "Corrección pedida por Secretaría", "aplicar_al_agente": None}))
        exigir(RegistroAsistencia.objects.get(pk=reg.pk).estado_registro == "BORRADOR", "no volvió a borrador")
        return "sin motivo se rechaza; con motivo vuelve a borrador"
    r.paso("Corregir un registro validado pide motivo", corregir_validado)
    r.entrar(bedelia)

    # ───── 10. Recepción ─────
    r.titulo("10. Recepción de formularios")
    url_rec = reverse("asistencia:recepcion_formularios")
    r.paso("Listado con cada filtro de justificación", lambda: (
        [r.abrir(url_rec, {"estado_justificacion": v}) for v in ("", "INJUSTIFICADA", "EN_TRAMITE", "JUSTIFICADA")],
        "4 filtros")[1])

    def recepcionar():
        reg = reg_bruno.last()
        f = formulario(r.abrir(reverse("asistencia:recepcionar_formulario", args=[reg.pk])), con=("estado_justificacion",))
        r.debe_guardar(r.enviar(f, {"estado_justificacion": "JUSTIFICADA", "nro_formulario": "F-100",
                                    "fecha_recepcion": martes.isoformat()}))
        reg.refresh_from_db()
        exigir(reg.estado_justificacion == "JUSTIFICADA" and reg.nro_formulario == "F-100",
               f"quedó {reg.estado_justificacion} / {reg.nro_formulario}")
        return "Bruno: formulario F-100, justificada"
    r.paso("Cargar el certificado de la falta de Bruno", recepcionar)

    # ───── 11. Pendientes ─────
    r.titulo("11. Pendientes (faltas sin resolver y licencias sin completar)")

    def pendiente(dni, fecha=None):
        for p in listar_pendientes():
            if p["persona"].pk == dni and (fecha is None or p["fecha"] == fecha):
                return p
        falla(f"no hay pendiente para {dni} {fecha or ''}")

    def resolver(p, **datos):
        # Se responde desde donde aparece: la planilla de hoy o, si se pospuso,
        # Licencias → Pendientes.
        donde = next((u for u in (url_pl, reverse("licencias:pendientes"))
                      if p["clave"] in r.abrir(u).content.decode()), None)
        exigir(donde, "el pendiente no aparece ni en la planilla ni en Licencias → Pendientes")
        return r.post(reverse("asistencia:resolver_pendiente"), {"clave": p["clave"], "volver": donde, **datos})

    def falta_bruno():
        quedan = [p for p in listar_pendientes() if p["persona"].pk == "99100002" and p["fecha"] == lunes]
        if not quedan:
            return "el certificado ya la resolvió"
        r.debe_avisar(resolver(quedan[0], accion="resolver", respuesta="formulario", nro_formulario="F-100"), "resolvió")
        return "el certificado cubrió una materia; se resolvió el pendiente del día"
    r.paso("Falta de Bruno del lunes (certificado recibido)", falta_bruno)
    r.paso("La falta de Elena de ayer figura como pendiente", lambda: f"estado {pendiente('99100005', ayer_habil)['estado']}")
    r.paso("Completar mañana (posponer)", lambda: r.debe_avisar(
        resolver(pendiente("99100005", ayer_habil), accion="posponer"), "pospuso"))
    r.paso("La licencia sin completar de Carla figura vencida", lambda: f"estado {pendiente('99100003', lunes)['estado']}")
    r.paso("Licencias → Pendientes con cada filtro", lambda: (
        [r.abrir(reverse("licencias:pendientes"), p) for p in (
            {}, {"tipo": "falta"}, {"tipo": "licencia"}, {"estado": "vencido"}, {"estado": "aviso"},
            {"estado": "en_plazo"}, {"q": "99100003"})], "7 filtros")[1])
    r.paso("Falta de Elena: «Llegó el formulario»", lambda: r.debe_avisar(resolver(
        pendiente("99100005", ayer_habil), accion="resolver", respuesta="formulario", nro_formulario="F-200"), "resolvió"))
    r.paso("Licencia de Darío (LT): «No corresponde» sin motivo se rechaza", lambda: r.debe_avisar(
        resolver(pendiente("99100004", martes), accion="resolver", respuesta="no_corresponde", motivo=""),
        "por qué no corresponde"))

    def no_corresponde():
        r.debe_avisar(resolver(pendiente("99100004", martes), accion="resolver", respuesta="no_corresponde",
                               motivo="No presentó certificado de largo tratamiento"), "resolvió")
        exigir(RegistroAsistencia.objects.filter(fecha=martes, designacion__persona_id="99100004",
                                                 marca__codigo="I").exists(), "la marca no pasó a inasistencia")
        return "pasó a inasistencia"
    r.paso("Licencia de Darío: «No corresponde» con motivo", no_corresponde)
    r.paso("La falta nueva de Darío: «No llegó»", lambda: r.debe_avisar(resolver(
        pendiente("99100004", martes), accion="resolver", respuesta="no_llego"), "resolvió"))

    # ───── 12. Licencias ─────
    r.titulo("12. Licencias")
    articulos = list(LicenciaArticulo.objects.filter(tipo_licencia__icontains="enfermedad").order_by("pk")) \
        or list(LicenciaArticulo.objects.order_by("pk"))
    art = {}
    for a in articulos:
        art.setdefault(a.sit_rev, a)
    url_nl = reverse("licencias:nueva_licencia")
    d_carla = Designacion.objects.filter(persona_id="99100003").first()

    def form_nueva_licencia(dni):
        return formulario(r.abrir(url_nl, {"persona": dni, "desde": lunes.isoformat()}), con=("persona", "desde"), metodo="post")

    def licencia_carla():
        articulo = art.get("Suplente") or articulos[0]
        r.debe_guardar(r.enviar(form_nueva_licencia("99100003"), {
            "accion": "guardar", "persona": "99100003", "articulo": str(articulo.pk),
            "desde": lunes.isoformat(), "hasta": miercoles.isoformat(), "designaciones": [str(d_carla.pk)],
            "disp_oficina": "1452", "disp_numero": "21", "disp_anio": str(hoy.year)}))
        exigir(LicenciaOtorgada.objects.filter(designacion=d_carla).exists(), "no se creó la licencia")
        return f"{articulo.cod_licencia} del {ddmmaaaa(lunes)} al {ddmmaaaa(miercoles)}"
    r.paso("Nueva licencia por docente (Carla, suplente)", licencia_carla)
    r.paso("La licencia completó el pendiente de Carla", lambda: exigir(
        not any(p["persona"].pk == "99100003" for p in listar_pendientes()), "Carla sigue con pendiente"))
    r.paso("Nueva licencia: Hasta anterior a Desde se rechaza", lambda: r.debe_rechazar(r.enviar(
        form_nueva_licencia("99100001"),
        {"accion": "guardar", "persona": "99100001", "articulo": str((art.get("Titular") or articulos[0]).pk),
         "desde": viernes.isoformat(), "hasta": jueves.isoformat(), "designaciones": [str(d_ana.pk)]}), "anterior"))

    def licencia_otorgada():
        f = formulario(r.abrir(reverse("licencias:nueva_licencia_otorgada")), con=("designacion", "articulo"))
        articulo = art.get("Titular") or articulos[0]
        r.debe_guardar(r.enviar(f, {
            "designacion": str(d_ana.pk), "articulo": str(articulo.pk), "sit_rev": "Titular",
            "desde": jueves.isoformat(), "hasta": viernes.isoformat(), "disp_tipo": "Disposición",
            "disp_oficina": "1452", "disp_numero": "22", "disp_anio": str(hoy.year),
            "nro_formulario": "F-300", "observaciones": "Alta por formulario individual"}))
        exigir(LicenciaOtorgada.objects.filter(designacion=d_ana).exists(), "no se creó")
        return "Ana, jueves a viernes"
    r.paso("Registrar licencia otorgada por designación (Ana)", licencia_otorgada)
    lic_ana = LicenciaOtorgada.objects.filter(designacion=d_ana).order_by("-pk").first()
    url_lis = reverse("licencias:listado_licencias_otorgadas")
    r.paso("Listado de licencias con cada filtro", lambda: (
        [r.abrir(url_lis, p) for p in ({}, {"docente": "flujo"}, {"fecha_desde": lunes.isoformat()},
                                         {"fecha_hasta": viernes.isoformat()})], "4 filtros")[1])
    if lic_ana:
        url_det = reverse("licencias:detalle_licencia", args=[lic_ana.pk])
        r.paso("Detalle de la licencia", lambda: contiene(r.abrir(url_det), "Materias y cargos afectados"))
        r.paso("Prorrogar la licencia", lambda: r.debe_guardar(r.enviar(
            formulario(r.abrir(url_det), accion="prorrogar"), {"nuevo_hasta": (viernes + timedelta(days=3)).isoformat()})))
        r.paso("Cortar la licencia antes", lambda: r.debe_guardar(r.enviar(
            formulario(r.abrir(url_det), accion="cortar"), {"volvio_el": (viernes + timedelta(days=3)).isoformat()})))
        r.paso("Editar la licencia", lambda: r.debe_guardar(r.enviar(formulario(
            r.abrir(reverse("licencias:editar_licencia_otorgada", args=[lic_ana.pk])), con=("designacion", "articulo")),
            {"observaciones": "Editada en el flujo"})))
        url_res = reverse("licencias:resoluciones_licencia", args=[lic_ana.pk])

        def adjuntar(nombre, contenido):
            f = formulario(r.abrir(url_res), con=("descripcion",))
            return r.enviar(f, {"descripcion": f"Resolución {nombre}"},
                            archivos={"archivo": SimpleUploadedFile(nombre, contenido)})
        r.paso("Adjuntar resolución en PDF", lambda: r.debe_guardar(adjuntar("res.pdf", b"%PDF-1.4\n%flujo\n")))
        r.paso("Adjuntar un archivo que no es PDF se rechaza", lambda: r.debe_rechazar(adjuntar("res.txt", b"hola"), "PDF"))

        def descargar():
            from licencias.models import ResolucionAdjunta
            res = ResolucionAdjunta.objects.order_by("-pk").first()
            exigir(res, "no hay resolución adjunta")
            return r.abrir(reverse("licencias:descargar_resolucion", args=[res.pk]))["Content-Type"]
        r.paso("Descargar la resolución", descargar)

    # ───── 13. Planilla mensual ─────
    r.titulo("13. Planilla mensual IL-01 / IL-02")
    url_pm = reverse("licencias:planilla_mensual", args=[lunes.year, lunes.month])
    r.paso("Abrir la planilla mensual", lambda: r.abrir(url_pm) and None)
    r.paso("Procesar el mes", lambda: r.debe_guardar(r.enviar(formulario(r.abrir(url_pm), accion="procesar"))))

    def guardar_renglones():
        f = formulario(r.abrir(url_pm), accion="guardar")
        cambios = {n: "Res. 55/2026" for n in f.nombres() if n.startswith("resolucion-")}
        exigir(cambios, "la planilla no tiene renglones para completar")
        return r.debe_guardar(r.enviar(f, cambios), "renglones")
    r.paso("Guardar artículos, oficina, año y resoluciones", guardar_renglones)
    r.paso("Emitir disposiciones", lambda: r.debe_guardar(r.enviar(formulario(r.abrir(url_pm), accion="emitir"))))

    def corregir_disposiciones():
        f = formulario(r.abrir(url_pm), accion="disposiciones")
        campo = next((n for n in sorted(f.nombres()) if n.startswith("disp-numero-")), None)
        exigir(campo, "no hay disposiciones para corregir")
        return r.debe_guardar(r.enviar(f, {campo: "900"}))
    r.paso("Corregir el número de una disposición", corregir_disposiciones)
    r.paso("Exportar la planilla a CSV", lambda: r.abrir(
        reverse("licencias:planilla_mensual_csv", args=[lunes.year, lunes.month]))["Content-Type"])
    r.paso("Reporte mensual de licencias (redirige a la planilla)", lambda: r.abrir(
        reverse("licencias:reporte_mensual_licencias", args=[lunes.year, lunes.month]), esperado=302)["Location"])
    r.paso("Generador de disposiciones", lambda: r.abrir(
        reverse("licencias:generador_disposiciones"), {"anio": lunes.year, "mes": lunes.month}, esperado=302) and None)
    anterior = (lunes.replace(day=1) - timedelta(days=1))
    siguiente = (lunes.replace(day=28) + timedelta(days=5))
    r.paso("Mes anterior y siguiente", lambda: (
        r.abrir(reverse("licencias:planilla_mensual", args=[anterior.year, anterior.month])),
        r.abrir(reverse("licencias:planilla_mensual", args=[siguiente.year, siguiente.month])), None)[2])

    # ───── 14. Cierres ─────
    r.titulo("14. Cierre de jornada y de mes")
    r.paso(f"Cerrar la jornada del lunes {ddmmaaaa(lunes)}", lambda: r.debe_guardar(
        r.post(reverse("asistencia:cerrar_jornada"), {"fecha": lunes.isoformat()})))
    r.paso("Cerrar la misma jornada otra vez se rechaza", lambda: r.debe_avisar(
        r.post(reverse("asistencia:cerrar_jornada"), {"fecha": lunes.isoformat()}), "ya está cerrada"))
    # Elena no tiene clase el lunes: aparece con «todos». A Darío se le deja
    # sin marca para que no tome la propuesta «Asistió».
    elena_lunes = {"agente-marca-99100005": marca["P"], "agente-horas-99100005": "2", "agente-marca-99100004": "",
                   "agente-obs-99100005": "Trámite personal"}
    r.paso("Permiso sin observaciones se rechaza", lambda: r.debe_rechazar(r.enviar(
        form_planilla(lunes, "todos"), {**elena_lunes, "agente-obs-99100005": "",
                                         "motivo": "Carga posterior al cierre del día"}), "requiere observaciones"))
    r.paso("Cargar en un día cerrado sin motivo se rechaza (Elena)", lambda: r.debe_rechazar(r.enviar(
        form_planilla(lunes, "todos"), {**elena_lunes, "motivo": ""}), "está cerrada: indicá el motivo"))
    r.paso("Cargar en un día cerrado con motivo (Elena)", lambda: r.debe_guardar(r.enviar(
        form_planilla(lunes, "todos"), {**elena_lunes, "motivo": "Carga posterior al cierre del día"})))
    url_cierre = reverse("asistencia:confirmar_cierre")
    r.paso("Cerrar el mes con registros sin validar se rechaza", lambda: r.debe_rechazar(r.enviar(
        formulario(r.abrir(url_cierre), con=("anio", "mes")),
        {"anio": str(lunes.year), "mes": str(lunes.month)}), "sin validar"))

    r.entrar(secretaria)

    def validar_todo():
        filtro = dict(fecha__year=lunes.year, fecha__month=lunes.month, estado_registro="BORRADOR")
        ids = list(RegistroAsistencia.objects.filter(**filtro).values_list("pk", flat=True))
        r.post(reverse("asistencia:validar_multiples"), {"registro_ids": [str(i) for i in ids], "next": url_hist})
        quedan = RegistroAsistencia.objects.filter(**filtro).count()
        exigir(quedan == 0, f"quedan {quedan} sin validar")
        return f"{len(ids)} registros validados"
    r.paso("Validar seleccionados (todo el mes)", validar_todo)

    def cerrar_mes():
        f = formulario(r.abrir(url_cierre), con=("anio", "mes"))
        r.debe_guardar(r.enviar(f, {"anio": str(lunes.year), "mes": str(lunes.month)}))
        exigir(CierreMensual.objects.filter(anio=lunes.year, mes=lunes.month, estado="CERRADO").exists(), "no quedó cerrado")
        return f"{lunes.month:02d}/{lunes.year} cerrado"
    r.paso("Cerrar el mes", cerrar_mes)
    r.paso("Listado de cierres", lambda: contiene(r.abrir(reverse("asistencia:lista_cierres")), "Cierres mensuales"))
    url_reab = reverse("asistencia:reapertura_mensual", args=[lunes.year, lunes.month])
    r.paso("Reabrir sin motivo se rechaza", lambda: r.debe_rechazar(r.enviar(
        formulario(r.abrir(url_reab), con=("motivo",)), {"motivo": ""}), "motivo"))
    r.paso("Reabrir el mes con motivo", lambda: r.debe_guardar(r.enviar(
        formulario(r.abrir(url_reab), con=("motivo",)), {"motivo": "Reapertura para corregir una licencia"})))

    # ───── 15. Reportes ─────
    r.titulo("15. Consultas, alertas y bitácora")
    url_con = reverse("reportes:consultas")
    filtros = [{}, {"dni": "99100003"}, {"apellido": "flujo"}, {"carrera": GE},
               {"carrera": GE, "espacio_curricular": materia["Legislación Laboral"]}, {"origen": "licencias"},
               {"origen": "ausencias"}, {"desde": lunes.isoformat(), "hasta": viernes.isoformat()},
               {"justifica": "si"}, {"justifica": "no"}]
    r.paso("Consultas con cada filtro", lambda: ([r.abrir(url_con, p) for p in filtros], f"{len(filtros)} búsquedas")[1])
    r.paso("Carrera y materia que no corresponden se rechaza", lambda: r.debe_rechazar(
        r.abrir(url_con, {"carrera": SW, "espacio_curricular": materia["Contabilidad"]}), "no pertenece"))
    r.paso("«Desde» posterior a «hasta» se rechaza", lambda: r.debe_rechazar(
        r.abrir(url_con, {"desde": viernes.isoformat(), "hasta": lunes.isoformat()}), "posterior"))
    r.paso("Exportar la consulta a CSV", lambda: r.abrir(url_con, {"dni": "99100003", "exportar": "csv"})["Content-Type"])

    def alertas(nombre, campos):
        f = formulario(r.abrir(reverse(f"reportes:{nombre}")), con=campos)
        variantes = [v for v, _ in f.opciones(campos[-1])] or [""]
        for valor in variantes:
            resp = r.enviar(f, {campos[-1]: valor})
            exigir(resp.status_code == 200, f"{campos[-1]}={valor} devolvió {resp.status_code}")
        return f"{len(variantes)} variantes"
    r.paso("Alertas: topes de licencias (cada umbral)", lambda: alertas("alertas", ("anio", "umbral")))
    r.paso("Alertas: inasistencias y permisos (cada umbral)", lambda: alertas("alertas_inasistencias", ("anio", "umbral")))
    r.paso("Alertas: licencias por vencer (cada plazo)", lambda: alertas("alertas_licencias_vencimiento", ("dias",)))
    r.paso("Alertas: designaciones por vencer (cada plazo)", lambda: alertas("alertas_designaciones", ("dias",)))

    def bitacora():
        url = reverse("reportes:bitacora")
        f = formulario(r.abrir(url), con=("accion",))
        acciones = [v for v, _ in f.opciones("accion") if v]
        for v in acciones:
            exigir(r.enviar(f, {"accion": v}).status_code == 200, f"acción {v}")
        r.abrir(url, {"usuario": "flujo", "dni": "99100002", "desde": lunes.isoformat(), "hasta": hoy.isoformat()})
        return f"{len(acciones)} tipos de acción"
    r.paso("Bitácora con cada filtro", bitacora)

    # ───── 16. Permisos ─────
    r.titulo("16. Permisos")
    sin_rol = U.objects.create_user("flujo.sinrol", password=CLAVE)
    r.entrar(sin_rol)
    protegidas = [reverse(n) for n in (
        "asistencia:registro_diario", "asistencia:planilla_rapida", "asistencia:historial", "personal:gestion_legajos",
        "personal:catalogos", "licencias:listado_licencias_otorgadas", "reportes:consultas", "reportes:usuarios",
        "reportes:parametros")]

    def sin_permiso():
        abiertas = [u for u in protegidas if r.cliente.get(u).status_code == 200]
        exigir(not abiertas, f"un usuario sin rol puede abrir {abiertas}")
        return f"{len(protegidas)} pantallas bloqueadas"
    r.paso("Un usuario sin rol no entra a ninguna pantalla", sin_permiso)

    # ───── 17. Barrido de pantallas ─────
    r.titulo("17. Barrido: todas las pantallas sin parámetros abren")
    r.entrar(bedelia)
    from django.urls import URLPattern, URLResolver, get_resolver

    def rutas(patrones, prefijo=""):
        for p in patrones:
            if isinstance(p, URLResolver):
                if p.namespace != "admin":
                    yield from rutas(p.url_patterns, prefijo + (p.namespace + ":" if p.namespace else ""))
            elif isinstance(p, URLPattern) and p.name and not p.pattern.regex.groups:
                yield prefijo + p.name
    for nombre in sorted(set(rutas(get_resolver().url_patterns)) - {"logout"}):
        def abrir_ruta(n=nombre):
            resp = r.cliente.get(reverse(n))
            # 400: datos_designacion necesita designación y fecha (respuesta JSON).
            permitidos = (200, 302, 405) + ((400,) if n == "asistencia:datos_designacion" else ())
            exigir(resp.status_code in permitidos, f"código {resp.status_code}")
            return str(resp.status_code)
        r.paso(f"GET {nombre}", abrir_ruta)

    # ───── 18. Mantenimiento ─────
    r.titulo("18. Comandos de mantenimiento")
    r.paso("cerrar_designaciones_vencidas", lambda: call_command("cerrar_designaciones_vencidas", verbosity=0))
    r.paso("emitir_disposiciones del mes", lambda: call_command(
        "emitir_disposiciones", str(lunes.year), str(lunes.month), verbosity=0))
    r.paso("purgar_sesiones", lambda: call_command("purgar_sesiones", dias=30, verbosity=0))


def main():
    runner = DiscoverRunner(interactive=False, verbosity=0)
    runner.setup_test_environment()
    print("Creando la base de prueba (puede tardar un minuto)…")
    viejas = runner.setup_databases()
    recorrido = Recorrido()
    try:
        flujo(recorrido)
    except SystemExit:
        pass
    except Exception:  # noqa: BLE001
        recorrido.fallas.append(("(general)", "El recorrido se cortó", traceback.format_exc()))
        print(traceback.format_exc())
    finally:
        runner.teardown_databases(viejas)
        runner.teardown_test_environment()

    total = recorrido.ok + len(recorrido.fallas)
    print("\n" + "=" * 70)
    print(f"RESULTADO: {recorrido.ok} de {total} pasos OK · {len(recorrido.fallas)} con falla")
    for seccion, paso, mensaje in recorrido.fallas:
        print(f"  - [{seccion}] {paso}\n      {mensaje.strip().splitlines()[0][:300]}")
    print("=" * 70)
    sys.exit(1 if recorrido.fallas else 0)


if __name__ == "__main__":
    main()
