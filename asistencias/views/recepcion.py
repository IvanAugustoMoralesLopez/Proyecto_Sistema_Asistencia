"""
Recepción del formulario en papel de las inasistencias (RF-09).
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from ..forms import FiltroRecepcionForm, RecepcionFormularioForm
from ..models import RegistroAsistencia
from ..services import recepcionar_formulario
from ._comun import _aplicar_filtros, _asegurar_sesion_edicion, _mensaje_error, _paginar


@login_required
def recepcion_formularios(request):
    """Inasistencias a la espera de formulario en papel (RF-09)."""
    form = FiltroRecepcionForm(request.GET or None)
    Justificacion = RegistroAsistencia.EstadoJustificacion

    registros = (
        RegistroAsistencia.objects.select_related(
            "designacion__persona",
            "designacion__cargo",
            "designacion__espacio_curricular",
            "marca",
            "recepcionado_por",
        )
        .filter(marca__computa_inasistencia=True)
        .order_by("-fecha", "designacion__persona__apellido_nombre")
    )

    estado = FiltroRecepcionForm.PENDIENTES

    if form.is_valid():
        datos = form.cleaned_data
        registros = _aplicar_filtros(registros, datos)
        estado = (
            datos.get("estado_justificacion")
            or FiltroRecepcionForm.PENDIENTES
        )

    if estado == FiltroRecepcionForm.PENDIENTES:
        registros = registros.filter(
            estado_justificacion__in=[
                Justificacion.INJUSTIFICADA,
                Justificacion.EN_TRAMITE,
            ]
        )
    elif estado != FiltroRecepcionForm.TODAS:
        registros = registros.filter(estado_justificacion=estado)

    pagina, querystring = _paginar(request, registros)

    return render(
        request,
        "asistencias/recepcion_formularios.html",
        {
            "form": form,
            "pagina": pagina,
            "querystring": querystring,
        },
    )


@login_required
@permission_required(
    "asistencias.recepcionar_formulario",
    raise_exception=True,
)
@require_http_methods(["GET", "POST"])
def recepcionar_formulario_view(request, pk):
    registro = get_object_or_404(
        RegistroAsistencia.objects.select_related(
            "designacion__persona",
            "designacion__cargo",
            "marca",
            "recepcionado_por",
        ),
        pk=pk,
    )

    if request.method == "POST":
        form = RecepcionFormularioForm(request.POST, registro=registro)

        if form.is_valid():
            datos = form.cleaned_data

            try:
                token = _asegurar_sesion_edicion(request)
                recepcionar_formulario(
                    usuario=request.user,
                    token=token,
                    registro_id=registro.pk,
                    nuevo_estado=datos["estado_justificacion"],
                    nro_formulario=datos["nro_formulario"],
                    fecha_recepcion=datos["fecha_recepcion"],
                    motivo=datos["motivo"],
                )
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _mensaje_error(exc))
            else:
                messages.success(
                    request,
                    "El estado de la inasistencia se actualizó.",
                )
                return redirect("asistencia:recepcion_formularios")
    else:
        form = RecepcionFormularioForm(registro=registro)

    return render(
        request,
        "asistencias/recepcionar_formulario.html",
        {
            "form": form,
            "registro": registro,
            "puede_recepcionar": bool(form.fields["estado_justificacion"].choices),
        },
    )
