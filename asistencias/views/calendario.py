"""
Calendario escolar (RF-10): consulta, alta, modificación y baja de
feriados, asuetos y días inhábiles.
"""

from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from ..forms import DiaNoLaborableForm
from ..models import DiaNoLaborable
from ..services import (
    ANIO_MAXIMO,
    ANIO_MINIMO,
    eliminar_dia_no_laborable,
    guardar_dia_no_laborable,
    registros_cargados,
)
from ._comun import _mensaje_error


def _anio_consultado(request):
    """Año del listado; si el parámetro no sirve, el año en curso."""
    actual = timezone.localdate().year

    try:
        anio = int(request.GET.get("anio", actual))
    except ValueError:
        return actual

    return anio if ANIO_MINIMO <= anio <= ANIO_MAXIMO else actual


def _volver_al_calendario(fecha):
    return redirect(
        f"{reverse('asistencia:lista_calendario')}?anio={fecha.year}"
    )


def _avisar_registros_existentes(request, fecha):
    cantidad = registros_cargados(fecha)

    if cantidad:
        messages.warning(
            request,
            f"Ya hay {cantidad} registro(s) de asistencia cargado(s) el "
            f"{fecha:%d/%m/%Y}: el calendario no los modifica.",
        )


@login_required
@permission_required(
    "asistencias.view_registroasistencia",
    raise_exception=True,
)
def lista_calendario(request):
    anio = _anio_consultado(request)

    dias = DiaNoLaborable.objects.filter(
        fecha__gte=date(anio, 1, 1),
        fecha__lte=date(anio, 12, 31),
    )

    return render(
        request,
        "asistencias/calendario.html",
        {
            "dias": dias,
            "anio": anio,
            "anio_anterior": anio - 1 if anio > ANIO_MINIMO else None,
            "anio_siguiente": anio + 1 if anio < ANIO_MAXIMO else None,
        },
    )


@login_required
@permission_required(
    "asistencias.add_dianolaborable",
    raise_exception=True,
)
@require_http_methods(["GET", "POST"])
def crear_dia_no_laborable(request):
    if request.method == "POST":
        form = DiaNoLaborableForm(request.POST)

        if form.is_valid():
            try:
                dia = guardar_dia_no_laborable(
                    usuario=request.user,
                    datos=form.cleaned_data,
                )
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _mensaje_error(exc))
            else:
                messages.success(
                    request,
                    f"Se cargó el {dia.fecha:%d/%m/%Y} en el calendario.",
                )
                _avisar_registros_existentes(request, dia.fecha)
                return _volver_al_calendario(dia.fecha)
    else:
        form = DiaNoLaborableForm()

    return render(
        request,
        "asistencias/formulario_calendario.html",
        {"form": form, "titulo": "Nuevo día del calendario"},
    )


@login_required
@permission_required(
    "asistencias.change_dianolaborable",
    raise_exception=True,
)
@require_http_methods(["GET", "POST"])
def editar_dia_no_laborable(request, pk):
    dia = get_object_or_404(DiaNoLaborable, pk=pk)

    if request.method == "POST":
        form = DiaNoLaborableForm(request.POST, instance=dia)

        if form.is_valid():
            try:
                actualizado = guardar_dia_no_laborable(
                    usuario=request.user,
                    datos=form.cleaned_data,
                    dia_id=pk,
                )
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _mensaje_error(exc))
            else:
                messages.success(
                    request,
                    f"Se actualizó el {actualizado.fecha:%d/%m/%Y} "
                    "del calendario.",
                )
                _avisar_registros_existentes(request, actualizado.fecha)
                return _volver_al_calendario(actualizado.fecha)
    else:
        form = DiaNoLaborableForm(instance=dia)

    return render(
        request,
        "asistencias/formulario_calendario.html",
        {"form": form, "titulo": "Editar día del calendario"},
    )


@login_required
@permission_required(
    "asistencias.delete_dianolaborable",
    raise_exception=True,
)
@require_POST
def eliminar_dia_no_laborable_view(request, pk):
    try:
        dia = eliminar_dia_no_laborable(usuario=request.user, dia_id=pk)
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _mensaje_error(exc))
        return redirect("asistencia:lista_calendario")

    messages.success(
        request,
        f"Se eliminó el {dia.fecha:%d/%m/%Y} del calendario.",
    )
    return _volver_al_calendario(dia.fecha)
