"""
Helpers compartidos por las vistas de asistencias: token/sesión de
edición, mensajes de error legibles, los filtros y la paginación que
usan Historial y Recepción de formularios, y las vistas de
liberación/renovación manual de sesión.
"""

import functools
import uuid
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from ..services import (
    MAX_OPERADORES,
    MINUTOS_EXPIRACION_SESION,
    adquirir_sesion_edicion,
    fecha_admitida,
    id_admitido,
    liberar_sesion_edicion,
    nombre_de,
    operadores_activos,
    renovar_sesion_edicion,
)


def _fecha_pedida(texto, por_defecto=None):
    """
    Fecha ISO recibida por GET/POST, o None si no sirve.

    Rechaza lo que no es una fecha y también las fechas fuera del rango que
    el sistema admite (año 2000 a 2100): con `date.max` o `date.min`, sumar o
    restar un día para los botones «anterior» y «siguiente» desborda el tipo
    `date` y la pantalla responde con un error 500.
    """
    if not texto:
        return por_defecto

    try:
        fecha = date.fromisoformat(texto)
    except (TypeError, ValueError):
        return None

    return fecha if fecha_admitida(fecha) else None


def _dia_vecino(fecha, dias):
    """Fecha corrida `dias` días, acotada al rango que el sistema admite."""
    try:
        vecina = fecha + timedelta(days=dias)
    except (OverflowError, ValueError):
        return fecha

    return vecina if fecha_admitida(vecina) else fecha


def _id_pedido(valor):
    """Id de base válido recibido del navegador, o None."""
    return id_admitido(valor)


def _ids_pedidos(valores):
    """Ids de base válidos de una lista recibida del navegador, sin repetir."""
    vistos = []
    for valor in valores:
        numero = id_admitido(valor)
        if numero is not None and numero not in vistos:
            vistos.append(numero)
    return vistos


def vista_protegida(permiso, *, methods=None):
    """login_required + permission_required + métodos HTTP en una línea."""
    def decorar(view_func):
        decorada = view_func
        if methods:
            decorada = require_http_methods(methods)(decorada)
        decorada = permission_required(permiso, raise_exception=True)(decorada)
        decorada = login_required(decorada)
        functools.update_wrapper(decorada, view_func)
        return decorada
    return decorar


def _token_edicion(request):
    token = request.session.get("asistencia_token")

    if not token:
        token = str(uuid.uuid4())
        request.session["asistencia_token"] = token

    return token


def _asegurar_sesion_edicion(request):
    token = _token_edicion(request)
    adquirir_sesion_edicion(request.user, token)
    return token


def contexto_sesion(request):
    """
    Quién está cargando asistencia ahora mismo, para la barra de la pantalla.

    El sistema admite dos personas a la vez; si no se muestra quiénes son, el
    tercero que entra no entiende por qué no puede trabajar (punto 1).
    """
    token = request.session.get("asistencia_token")
    activos = operadores_activos()
    mio = next((s for s in activos if str(s.token) == str(token)), None)

    return {
        "sesion_operadores": [
            {
                "nombre": nombre_de(s.usuario),
                "soy_yo": str(s.token) == str(token),
                "expira_en": s.expira_en,
            }
            for s in activos
        ],
        "sesion_tengo_lugar": mio is not None,
        "sesion_expira_en": mio.expira_en if mio else None,
        "sesion_maximo": MAX_OPERADORES,
        "sesion_minutos": MINUTOS_EXPIRACION_SESION,
        "sesion_libres": max(MAX_OPERADORES - len(activos), 0),
    }


def _mensaje_error(exc):
    """
    Texto legible de una excepción esperada. str() de una ValidationError
    devuelve la representación de la lista o del diccionario de errores.
    """
    if isinstance(exc, ValidationError):
        return " ".join(exc.messages)

    return str(exc)


def _url_segura(url):
    """Solo URLs relativas del mismo sitio (previene open redirect)."""
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts=set()):
        return url
    return ""


def _aplicar_filtros(registros, datos):
    """Filtros comunes del historial y de la recepción de formularios."""
    if datos.get("dni"):
        registros = registros.filter(
            designacion__persona__dni__icontains=datos["dni"]
        )

    if datos.get("apellido_nombre"):
        registros = registros.filter(
            designacion__persona__apellido_nombre__icontains=(
                datos["apellido_nombre"]
            )
        )

    if datos.get("desde"):
        registros = registros.filter(fecha__gte=datos["desde"])

    if datos.get("hasta"):
        registros = registros.filter(fecha__lte=datos["hasta"])

    if datos.get("marca"):
        registros = registros.filter(marca=datos["marca"])

    if datos.get("espacio_curricular"):
        registros = registros.filter(
            designacion__espacio_curricular=datos["espacio_curricular"]
        )

    if datos.get("estado_registro"):
        registros = registros.filter(
            estado_registro=datos["estado_registro"]
        )

    return registros


def _paginar(request, registros):
    paginador = Paginator(registros, 25)
    pagina = paginador.get_page(request.GET.get("page"))

    parametros = request.GET.copy()
    parametros.pop("page", None)

    return pagina, parametros.urlencode()


# --- Vistas de sesión de edición ---


@login_required
@require_POST
def liberar_edicion(request):
    token = request.session.get("asistencia_token")

    if token:
        liberar_sesion_edicion(request.user, token)
        request.session.pop("asistencia_token", None)

    messages.info(
        request,
        "Liberaste tu lugar. Otra persona ya puede cargar asistencia. "
        "Vos podés volver a entrar cuando quieras.",
    )
    destino = _url_segura(request.POST.get("next", ""))
    return redirect(destino or "asistencia:registro_diario")


@login_required
@require_POST
def renovar_edicion(request):
    token = request.session.get("asistencia_token")

    try:
        renovar_sesion_edicion(request.user, token)
    except (ValidationError, PermissionDenied) as exc:
        return render(
            request,
            "asistencias/error_sesion.html",
            {"mensaje": _mensaje_error(exc)},
            status=409,
        )

    return redirect("asistencia:registro_diario")
