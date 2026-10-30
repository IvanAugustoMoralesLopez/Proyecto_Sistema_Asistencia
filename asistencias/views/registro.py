"""
Registro diario (consulta por fecha), alta/edición individual de una
asistencia, historial con filtros y validación de registros.
"""

from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from ..forms import FiltroAsistenciaForm, RegistroAsistenciaForm
from ..models import CierreDiario, CierreMensual, EventoAsistencia, RegistroAsistencia
from ..services import guardar_asistencia, motivo_dia_no_laborable, validar_asistencia
from ._comun import _aplicar_filtros, _asegurar_sesion_edicion, _mensaje_error, _paginar


@login_required
def registro_diario(request):
    fecha_seleccionada = request.GET.get(
        "fecha",
        date.today().isoformat(),
    )

    try:
        fecha_objeto = date.fromisoformat(fecha_seleccionada)
    except ValueError:
        messages.error(request, "La fecha seleccionada no es válida.")
        return redirect("asistencia:registro_diario")

    registros = (
        RegistroAsistencia.objects.select_related(
            "designacion__persona",
            "designacion__cargo",
            "designacion__espacio_curricular",
            "marca",
            "licencia",
        )
        .filter(fecha=fecha_objeto)
        .order_by(
            "designacion__persona__apellido_nombre",
            "designacion_id",
        )
    )

    cierre = CierreMensual.objects.filter(
        anio=fecha_objeto.year,
        mes=fecha_objeto.month,
    ).first()
    jornada_cerrada = (
        CierreDiario.objects.select_related("cerrado_por")
        .filter(fecha=fecha_objeto)
        .first()
    )
    motivo_no_laborable = motivo_dia_no_laborable(fecha_objeto)
    periodo_cerrado = bool(
        cierre and cierre.estado == CierreMensual.Estado.CERRADO
    )

    puede_cerrar_jornada = (
        request.user.has_perm("asistencias.cerrar_jornada")
        and jornada_cerrada is None
        and not motivo_no_laborable
        and not periodo_cerrado
        and fecha_objeto <= timezone.localdate()
    )

    return render(
        request,
        "asistencias/registro_diario.html",
        {
            "registros": registros,
            "fecha_seleccionada": fecha_objeto.isoformat(),
            "cierre": cierre,
            "jornada_cerrada": jornada_cerrada,
            "puede_cerrar_jornada": puede_cerrar_jornada,
            "motivo_no_laborable": motivo_no_laborable,
        },
    )


@login_required
@permission_required(
    "asistencias.add_registroasistencia",
    raise_exception=True,
)
@require_http_methods(["GET", "POST"])
def crear_asistencia(request):
    if request.method == "POST":
        form = RegistroAsistenciaForm(request.POST)

        if form.is_valid():
            try:
                token = _asegurar_sesion_edicion(request)
                registro = guardar_asistencia(
                    usuario=request.user,
                    token=token,
                    datos=form.cleaned_data,
                    motivo=request.POST.get("motivo", ""),
                )
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _mensaje_error(exc))
            else:
                messages.success(
                    request,
                    "La asistencia se guardó correctamente.",
                )
                return redirect(
                    f"{reverse('asistencia:registro_diario')}"
                    f"?fecha={registro.fecha.isoformat()}"
                )
    else:
        form = RegistroAsistenciaForm(
            initial={"fecha": date.today()}
        )

    return render(
        request,
        "asistencias/formulario_asistencia.html",
        {
            "form": form,
            "titulo": "Registrar asistencia",
        },
    )


@login_required
@permission_required(
    "asistencias.change_registroasistencia",
    raise_exception=True,
)
@require_http_methods(["GET", "POST"])
def editar_asistencia(request, pk):
    registro = get_object_or_404(
        RegistroAsistencia.objects.select_related(
            "designacion",
            "marca",
            "licencia",
        ),
        pk=pk,
    )

    if request.method == "POST":
        form = RegistroAsistenciaForm(
            request.POST,
            instance=registro,
        )

        if form.is_valid():
            try:
                token = _asegurar_sesion_edicion(request)
                actualizado = guardar_asistencia(
                    usuario=request.user,
                    token=token,
                    datos=form.cleaned_data,
                    registro_id=registro.pk,
                    motivo=request.POST.get("motivo", ""),
                )
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _mensaje_error(exc))
            else:
                messages.success(
                    request,
                    "La asistencia se actualizó correctamente.",
                )
                return redirect("asistencia:historial")
    else:
        form = RegistroAsistenciaForm(instance=registro)

    return render(
        request,
        "asistencias/formulario_asistencia.html",
        {
            "form": form,
            "registro": registro,
            "titulo": "Editar asistencia",
        },
    )


@login_required
def historial(request):
    form = FiltroAsistenciaForm(request.GET or None)

    registros = (
        RegistroAsistencia.objects.select_related(
            "designacion__persona",
            "designacion__cargo",
            "marca",
            "actualizado_por",
        )
        .all()
        .order_by("-fecha", "designacion__persona__apellido_nombre")
    )

    if form.is_valid():
        datos = form.cleaned_data
        registros = _aplicar_filtros(registros, datos)

        if datos.get("estado_justificacion"):
            registros = registros.filter(
                estado_justificacion=datos["estado_justificacion"]
            )

    pagina, querystring = _paginar(request, registros)

    return render(
        request,
        "asistencias/historial.html",
        {
            "form": form,
            "pagina": pagina,
            "querystring": querystring,
        },
    )


@login_required
def detalle_asistencia(request, pk):
    registro = get_object_or_404(
        RegistroAsistencia.objects.select_related(
            "designacion__persona",
            "designacion__cargo",
            "marca",
            "licencia",
            "creado_por",
            "actualizado_por",
        ),
        pk=pk,
    )

    eventos = EventoAsistencia.objects.filter(
        asistencia=registro,
    ).select_related("usuario")

    return render(
        request,
        "asistencias/detalle_asistencia.html",
        {
            "registro": registro,
            "eventos": eventos,
        },
    )


@login_required
@permission_required(
    "asistencias.validar_registro",
    raise_exception=True,
)
@require_POST
def validar_registro(request, pk):
    try:
        token = _asegurar_sesion_edicion(request)
        validar_asistencia(
            usuario=request.user,
            token=token,
            registro_id=pk,
        )
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _mensaje_error(exc))
    else:
        messages.success(request, "El registro quedó validado.")

    return redirect("asistencia:historial")
