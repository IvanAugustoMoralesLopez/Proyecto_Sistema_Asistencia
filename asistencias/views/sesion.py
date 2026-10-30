"""
Liberación y renovación manual de la sesión de edición (ver
`asistencias.services.sesiones`).
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from ..services import liberar_sesion_edicion, renovar_sesion_edicion
from ._comun import _mensaje_error


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
