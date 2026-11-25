"""
Resolver pendientes (faltas sin resolver y licencias sin completar) desde
el aviso de la carga diaria o desde Licencias › Pendientes.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect
from django.urls import reverse

from ..services import posponer_pendiente, resolver_pendiente
from ._comun import _asegurar_sesion_edicion, _mensaje_error, _url_segura, vista_protegida


@vista_protegida("asistencias.change_registroasistencia", methods=["POST"])
def resolver_pendiente_view(request):
    """POST con clave, accion (posponer | resolver), respuesta y volver."""
    volver = _url_segura(request.POST.get("volver", "")) or reverse(
        "asistencia:planilla_rapida"
    )
    clave = request.POST.get("clave", "")
    accion = request.POST.get("accion", "")

    try:
        token = _asegurar_sesion_edicion(request)
        if accion == "posponer":
            pendiente = posponer_pendiente(usuario=request.user, token=token, clave=clave)
            messages.info(
                request,
                f"Se pospuso hasta el {pendiente['vence']:%d/%m/%Y}: "
                "ese día la respuesta es obligatoria.",
            )
        elif accion == "resolver":
            pendiente = resolver_pendiente(
                usuario=request.user,
                token=token,
                clave=clave,
                respuesta=request.POST.get("respuesta", ""),
                nro_formulario=request.POST.get("nro_formulario", ""),
                motivo=request.POST.get("motivo", ""),
                nueva_marca=request.POST.get("nueva_marca", ""),
            )
            texto = (
                f"Se resolvió el pendiente de {pendiente['persona'].apellido_nombre} "
                f"del {pendiente['fecha']:%d/%m/%Y}."
            )
            marca_nueva = pendiente.get("marca_nueva")
            if marca_nueva is not None:
                texto += f" La falta pasó a {marca_nueva.descripcion} ({marca_nueva.codigo})."
                if marca_nueva.codigo in ("LIC", "LT"):
                    texto += " Falta cargar la licencia: sigue en Pendientes."
            messages.success(request, texto)
        else:
            raise ValidationError("Acción no válida.")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _mensaje_error(exc))

    return redirect(volver)
