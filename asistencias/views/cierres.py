"""
Cierre de la jornada diaria, listado de cierres y cierre/reapertura de
períodos mensuales.
"""

from datetime import date

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from ..forms import CierreMensualForm, ReaperturaMensualForm
from ..models import CierreDiario, CierreMensual, RegistroAsistencia
from ..services import cerrar_dia, cerrar_mes, reabrir_mes
from ._comun import _asegurar_sesion_edicion, _mensaje_error, vista_protegida


@vista_protegida("asistencias.cerrar_jornada", methods=["POST"])
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


@vista_protegida("asistencias.view_registroasistencia")
def lista_cierres(request):
    anio_filtro = request.GET.get("anio", "")

    cierres = CierreMensual.objects.select_related(
        "cerrado_por",
        "reabierto_por",
    ).all()

    if anio_filtro and anio_filtro.isdecimal():
        cierres = cierres.filter(anio=int(anio_filtro))

    cierres_diarios = CierreDiario.objects.select_related("cerrado_por")[:15]

    return render(
        request,
        "asistencias/cierres.html",
        {
            "cierres": cierres,
            "cierres_diarios": cierres_diarios,
            "anio_filtro": anio_filtro,
        },
    )


@vista_protegida("asistencias.cerrar_periodo", methods=["GET", "POST"])
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

    resumen = None
    if request.method == "GET" or (request.method == "POST" and not form.is_valid()):
        hoy = timezone.localdate()
        anio_prev = form.data.get("anio", str(hoy.year))
        mes_prev = form.data.get("mes", str(hoy.month))
        if anio_prev.isdecimal() and mes_prev.isdecimal():
            qs = RegistroAsistencia.objects.filter(
                fecha__year=int(anio_prev),
                fecha__month=int(mes_prev),
            )
            total = qs.count()
            borradores = qs.filter(
                estado_registro=RegistroAsistencia.Estado.BORRADOR
            ).count()
            validados = total - borradores
            resumen = {
                "total": total,
                "borradores": borradores,
                "validados": validados,
            }

    return render(
        request,
        "asistencias/confirmar_cierre.html",
        {"form": form, "resumen": resumen},
    )


@vista_protegida("asistencias.change_cierremensual", methods=["GET", "POST"])
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
            "titulo": "Reabrir período mensual",
            "url_cancelar": reverse("asistencia:lista_cierres"),
            "btn_texto": "Confirmar reapertura",
            "btn_clase": "danger",
        },
    )
