"""
Calendario escolar (RF-10): consulta, alta, modificación y baja de
feriados, asuetos y días inhábiles.
"""

from datetime import date

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from ..forms import CargaMasivaCalendarioForm, CopiarCalendarioForm, DiaNoLaborableForm
from ..models import DiaNoLaborable
from ..services import (
    ANIO_MAXIMO,
    ANIO_MINIMO,
    cargar_calendario_masivo,
    copiar_calendario,
    eliminar_dia_no_laborable,
    guardar_dia_no_laborable,
    registros_cargados,
)
from ._comun import _mensaje_error, vista_protegida


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


@vista_protegida("asistencias.view_registroasistencia")
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


@vista_protegida("asistencias.add_dianolaborable", methods=["GET", "POST"])
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
        {
            "form": form,
            "titulo": "Nuevo día del calendario",
            "url_cancelar": reverse("asistencia:lista_calendario"),
        },
    )


@vista_protegida("asistencias.change_dianolaborable", methods=["GET", "POST"])
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
        {
            "form": form,
            "titulo": "Editar día del calendario",
            "url_cancelar": reverse("asistencia:lista_calendario"),
        },
    )


@vista_protegida("asistencias.delete_dianolaborable", methods=["POST"])
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


@vista_protegida("asistencias.add_dianolaborable", methods=["GET", "POST"])
def cargar_masivo(request):
    if request.method == "POST":
        form = CargaMasivaCalendarioForm(request.POST)

        if form.is_valid():
            try:
                creados, errores = cargar_calendario_masivo(
                    usuario=request.user,
                    texto=form.cleaned_data["fechas"],
                    tipo=form.cleaned_data["tipo"],
                )
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _mensaje_error(exc))
            else:
                if creados:
                    messages.success(
                        request,
                        f"Se cargaron {creados} día(s) al calendario.",
                    )
                if errores:
                    for error in errores[:10]:
                        messages.warning(request, error)
                if not creados and not errores:
                    messages.info(
                        request,
                        "Todas las fechas ya estaban cargadas.",
                    )
                return redirect("asistencia:lista_calendario")
    else:
        form = CargaMasivaCalendarioForm()

    return render(
        request,
        "asistencias/cargar_masivo_calendario.html",
        {
            "form": form,
            "titulo": "Carga masiva de días no laborables",
            "url_cancelar": reverse("asistencia:lista_calendario"),
        },
    )


@vista_protegida("asistencias.add_dianolaborable", methods=["GET", "POST"])
def copiar_calendario_view(request):
    if request.method == "POST":
        form = CopiarCalendarioForm(request.POST)

        if form.is_valid():
            try:
                creados, omitidos = copiar_calendario(
                    usuario=request.user,
                    anio_origen=form.cleaned_data["anio_origen"],
                    anio_destino=form.cleaned_data["anio_destino"],
                )
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _mensaje_error(exc))
            else:
                msg = f"Se copiaron {creados} día(s)."
                if omitidos:
                    msg += f" {omitidos} ya existían o no aplican."
                messages.success(request, msg)
                return redirect(
                    f"{reverse('asistencia:lista_calendario')}"
                    f"?anio={form.cleaned_data['anio_destino']}"
                )
    else:
        anio_actual = timezone.localdate().year
        form = CopiarCalendarioForm(
            initial={
                "anio_origen": anio_actual,
                "anio_destino": anio_actual + 1,
            }
        )

    return render(
        request,
        "asistencias/copiar_calendario.html",
        {
            "form": form,
            "titulo": "Copiar calendario entre años",
            "url_cancelar": reverse("asistencia:lista_calendario"),
        },
    )
