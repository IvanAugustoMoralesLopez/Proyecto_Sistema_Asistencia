"""
Cierre de la jornada diaria, listado de cierres y cierre/reapertura de
períodos mensuales.
"""

from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from ..forms import CierreMensualForm, ReaperturaMensualForm
from ..models import CierreDiario, CierreMensual
from ..services import cerrar_dia, cerrar_mes, reabrir_mes
from ._comun import _asegurar_sesion_edicion, _mensaje_error


@login_required
@permission_required(
    "asistencias.cerrar_jornada",
    raise_exception=True,
)
@require_POST
def cerrar_jornada(request):
    try:
        fecha = date.fromisoformat(request.POST.get("fecha", ""))
    except ValueError:
        messages.error(request, "La fecha seleccionada no es válida.")
        return redirect("asistencia:registro_diario")

    try:
        token = _asegurar_sesion_edicion(request)
        cerrar_dia(usuario=request.user, token=token, fecha=fecha)
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _mensaje_error(exc))
    else:
        messages.success(
            request,
            f"Se cerró la jornada del {fecha:%d/%m/%Y}.",
        )

    return redirect(
        f"{reverse('asistencia:registro_diario')}"
        f"?fecha={fecha.isoformat()}"
    )


@login_required
@permission_required(
    "asistencias.view_registroasistencia",
    raise_exception=True,
)
def lista_cierres(request):
    cierres = CierreMensual.objects.select_related(
        "cerrado_por",
        "reabierto_por",
    ).all()
    cierres_diarios = CierreDiario.objects.select_related("cerrado_por")[:15]

    return render(
        request,
        "asistencias/cierres.html",
        {"cierres": cierres, "cierres_diarios": cierres_diarios},
    )


@login_required
@permission_required(
    "asistencias.cerrar_periodo",
    raise_exception=True,
)
@require_http_methods(["GET", "POST"])
def confirmar_cierre(request):
    if request.method == "POST":
        form = CierreMensualForm(request.POST)

        if form.is_valid():
            try:
                token = _asegurar_sesion_edicion(request)
                cierre = cerrar_mes(
                    usuario=request.user,
                    token=token,
                    anio=form.cleaned_data["anio"],
                    mes=form.cleaned_data["mes"],
                )
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _mensaje_error(exc))
            else:
                messages.success(
                    request,
                    f"Se cerró el período {cierre.anio}-{cierre.mes:02d}.",
                )
                return redirect("asistencia:lista_cierres")
    else:
        hoy = timezone.localdate()
        form = CierreMensualForm(
            initial={"anio": hoy.year, "mes": hoy.month}
        )

    return render(
        request,
        "asistencias/confirmar_cierre.html",
        {"form": form},
    )


@login_required
@permission_required(
    "asistencias.change_cierremensual",
    raise_exception=True,
)
@require_http_methods(["GET", "POST"])
def reapertura_mensual(request, anio, mes):
    cierre = get_object_or_404(
        CierreMensual,
        anio=anio,
        mes=mes,
    )

    if request.method == "POST":
        form = ReaperturaMensualForm(request.POST)

        if form.is_valid():
            try:
                token = _asegurar_sesion_edicion(request)
                reabrir_mes(
                    usuario=request.user,
                    token=token,
                    anio=anio,
                    mes=mes,
                    motivo=form.cleaned_data["motivo"],
                )
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _mensaje_error(exc))
            else:
                messages.success(
                    request,
                    "El período fue reabierto.",
                )
                return redirect("asistencia:lista_cierres")
    else:
        form = ReaperturaMensualForm()

    return render(
        request,
        "asistencias/reapertura_mensual.html",
        {
            "form": form,
            "cierre": cierre,
        },
    )
