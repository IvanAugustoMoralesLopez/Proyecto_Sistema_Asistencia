
import uuid
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from .forms import (
    RegistroAsistenciaForm,
    FiltroAsistenciaForm,
    CierreMensualForm,
    ReaperturaMensualForm,
)
from .models import (
    RegistroAsistencia,
    CierreMensual,
    EventoAsistencia,
)
from .services import (
    adquirir_sesion_edicion,
    renovar_sesion_edicion,
    liberar_sesion_edicion,
    guardar_asistencia,
    validar_asistencia,
    cerrar_mes,
    reabrir_mes,
)


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


@login_required
def registro_diario(request):
    fecha_seleccionada = request.GET.get(
        "fecha",
        date.today().isoformat(),
    )

    form = FiltroAsistenciaForm(
        initial={
            "desde": fecha_seleccionada,
            "hasta": fecha_seleccionada,
        }
    )

    registros = (
        RegistroAsistencia.objects.select_related(
            "designacion__persona",
            "designacion__cargo",
            "designacion__espacio_curricular",
            "marca",
            "licencia",
        )
        .filter(fecha=fecha_seleccionada)
        .order_by(
            "designacion__persona__apellido_nombre",
            "designacion_id",
        )
    )

    cierre = None

    try:
        fecha_objeto = date.fromisoformat(fecha_seleccionada)
        cierre = CierreMensual.objects.filter(
            anio=fecha_objeto.year,
            mes=fecha_objeto.month,
        ).first()
    except ValueError:
        messages.error(request, "La fecha seleccionada no es válida.")
        return redirect("asistencia:registro_diario")

    return render(
        request,
        "asistencias/registro_diario.html",
        {
            "registros": registros,
            "fecha_seleccionada": fecha_seleccionada,
            "cierre": cierre,
            "form": form,
        },
    )


@login_required
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
                )
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, str(exc))
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
                messages.error(request, str(exc))
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

    paginador = Paginator(registros, 25)
    pagina = paginador.get_page(request.GET.get("page"))

    return render(
        request,
        "asistencias/historial.html",
        {
            "form": form,
            "pagina": pagina,
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
        messages.error(request, str(exc))
    else:
        messages.success(request, "El registro quedó validado.")

    return redirect("asistencia:historial")


@login_required
def lista_cierres(request):
    cierres = CierreMensual.objects.select_related(
        "cerrado_por",
        "reabierto_por",
    ).all()

    return render(
        request,
        "asistencias/cierres.html",
        {"cierres": cierres},
    )


@login_required
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
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    f"Se cerró el período {cierre.anio}-{cierre.mes:02d}.",
                )
                return redirect("asistencia:lista_cierres")
    else:
        hoy = date.today()
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
                messages.error(request, str(exc))
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
            {"mensaje": str(exc)},
            status=409,
        )

    return redirect("asistencia:registro_diario")
