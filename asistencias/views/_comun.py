"""
Helpers compartidos por las vistas de asistencias: token/sesión de
edición, mensajes de error legibles, los filtros y la paginación que
usan Historial y Recepción de formularios, y las vistas de
liberación/renovación manual de sesión.
"""

import functools
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from ..services import (
    adquirir_sesion_edicion,
    liberar_sesion_edicion,
    renovar_sesion_edicion,
)


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

    messages.info(request, "Se liberó la sesión de edición.")
    return redirect("asistencia:registro_diario")


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
