"""
Helpers compartidos por las vistas de asistencias: token/sesión de
edición, mensajes de error legibles, y los filtros y la paginación que
usan Historial y Recepción de formularios.
"""

import uuid

from django.core.exceptions import ValidationError
from django.core.paginator import Paginator

from ..services import adquirir_sesion_edicion


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

    return registros


def _paginar(request, registros):
    paginador = Paginator(registros, 25)
    pagina = paginador.get_page(request.GET.get("page"))

    # Los enlaces de paginación conservan los filtros aplicados.
    parametros = request.GET.copy()
    parametros.pop("page", None)

    return pagina, parametros.urlencode()
