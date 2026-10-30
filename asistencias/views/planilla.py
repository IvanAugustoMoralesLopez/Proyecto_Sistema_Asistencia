"""
Planilla rápida: carga de todas las marcas del día en una sola pantalla
(RF-07).
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from licencias.models import LicenciaOtorgada
from personal.models import Designacion

from ..models import (
    CierreDiario,
    CierreMensual,
    MarcaAsistencia,
    RegistroAsistencia,
    licencia_cubre_fecha,
)
from ..services import PlanillaConErrores, guardar_planilla, motivo_dia_no_laborable
from ._comun import _asegurar_sesion_edicion, _mensaje_error


def _designaciones_del_dia(fecha, texto=""):
    """Designaciones vigentes en la fecha, ordenadas por docente."""
    designaciones = (
        Designacion.objects.filter(
            activo=True,
            persona__activa=True,
            desde__lte=fecha,
        )
        .filter(Q(hasta__isnull=True) | Q(hasta__gte=fecha))
        .select_related("persona", "cargo", "espacio_curricular")
        .order_by("persona__apellido_nombre", "persona_id", "id")
    )

    if texto:
        designaciones = designaciones.filter(
            Q(persona__apellido_nombre__icontains=texto)
            | Q(persona__dni__icontains=texto)
        )

    return designaciones


def _armar_filas(fecha, texto, valores, errores):
    """Una fila por designación vigente, con lo ya cargado y lo enviado."""
    designaciones = list(_designaciones_del_dia(fecha, texto))
    ids = [designacion.pk for designacion in designaciones]

    existentes = {
        registro.designacion_id: registro
        for registro in RegistroAsistencia.objects.select_related(
            "marca"
        ).filter(fecha=fecha, designacion_id__in=ids)
    }

    licencias = defaultdict(list)
    vigentes = (
        LicenciaOtorgada.objects.select_related("articulo")
        .filter(designacion_id__in=ids, desde__lte=fecha)
        .filter(Q(hasta__isnull=True) | Q(hasta__gte=fecha))
    )

    for licencia in vigentes:
        licencias[licencia.designacion_id].append(licencia)

    filas = []
    docente_anterior = None

    for designacion in designaciones:
        filas.append(
            {
                "designacion": designacion,
                "registro": existentes.get(designacion.pk),
                "licencias": licencias.get(designacion.pk, []),
                "valores": valores.get(designacion.pk, {}),
                "error": errores.get(designacion.pk),
                "primera_del_docente": (
                    designacion.persona_id != docente_anterior
                ),
            }
        )
        docente_anterior = designacion.persona_id

    return filas


def _leer_planilla(post, fecha):
    """
    Interpreta lo enviado por la planilla. Devuelve las filas listas para
    guardar, los valores enviados (para volver a mostrarlos) y los errores
    por designación.
    """
    prefijo = "marca-"
    ids = sorted(
        int(clave[len(prefijo):])
        for clave in post
        if clave.startswith(prefijo)
        and clave[len(prefijo):].isdigit()
        and post[clave]
    )

    designaciones = {
        designacion.pk: designacion
        for designacion in _designaciones_del_dia(fecha).filter(pk__in=ids)
    }
    marcas = {marca.pk: marca for marca in MarcaAsistencia.vigentes()}

    filas = []
    valores = {}
    errores = {}

    for pk in ids:
        marca_texto = post.get(f"marca-{pk}", "")
        horas_texto = post.get(f"horas-{pk}", "").strip()
        licencia_texto = post.get(f"licencia-{pk}", "")
        observaciones = post.get(f"obs-{pk}", "").strip()

        valores[pk] = {
            "marca": marca_texto,
            "horas": horas_texto,
            "licencia": licencia_texto,
            "obs": observaciones,
        }

        designacion = designaciones.get(pk)

        if designacion is None:
            errores[pk] = "La designación no está vigente en esta fecha."
            continue

        marca = marcas.get(int(marca_texto)) if marca_texto.isdigit() else None

        if marca is None:
            errores[pk] = "La marca elegida no es válida."
            continue

        try:
            horas = (
                Decimal(horas_texto.replace(",", "."))
                if horas_texto
                else Decimal("0")
            )
        except InvalidOperation:
            horas = None

        if horas is None or not horas.is_finite() or horas < 0:
            errores[pk] = "Las horas deben ser un número mayor o igual a cero."
            continue

        licencia = None

        if licencia_texto:
            licencia = (
                LicenciaOtorgada.objects.filter(
                    pk=int(licencia_texto), designacion=designacion
                ).first()
                if licencia_texto.isdigit()
                else None
            )

            if licencia is None or not licencia_cubre_fecha(licencia, fecha):
                errores[pk] = "La licencia elegida no es válida para esta fecha."
                continue

        filas.append(
            {
                "designacion": designacion,
                "marca": marca,
                "horas_inasistidas": horas,
                "licencia": licencia,
                "observaciones": observaciones,
            }
        )

    return filas, valores, errores


@login_required
@permission_required(
    "asistencias.add_registroasistencia",
    raise_exception=True,
)
@require_http_methods(["GET", "POST"])
def planilla_rapida(request):
    """Planilla de marcado del día: una fila por designación vigente."""
    origen = request.POST if request.method == "POST" else request.GET

    try:
        fecha = date.fromisoformat(
            origen.get("fecha", timezone.localdate().isoformat())
        )
    except ValueError:
        messages.error(request, "La fecha seleccionada no es válida.")
        return redirect("asistencia:planilla_rapida")

    texto = origen.get("q", "").strip()

    cierre = CierreMensual.objects.filter(
        anio=fecha.year,
        mes=fecha.month,
    ).first()
    jornada_cerrada = (
        CierreDiario.objects.select_related("cerrado_por")
        .filter(fecha=fecha)
        .first()
    )
    motivo_no_laborable = motivo_dia_no_laborable(fecha)
    puede_modificar_cerrada = request.user.has_perm(
        "asistencias.modificar_jornada_cerrada"
    )

    # Motivo por el que la planilla no se puede guardar, si lo hay.
    if fecha > timezone.localdate():
        bloqueo = "No se puede registrar asistencia de una fecha futura."
    elif motivo_no_laborable:
        bloqueo = f"{motivo_no_laborable}: no corresponde registrar asistencia."
    elif cierre and cierre.estado == CierreMensual.Estado.CERRADO:
        bloqueo = "El período está cerrado. Solicitá una reapertura autorizada."
    elif jornada_cerrada and not puede_modificar_cerrada:
        bloqueo = (
            "La jornada está cerrada: modificarla requiere autorización "
            "de Secretaría o Subsecretaría."
        )
    else:
        bloqueo = None

    valores = {}
    errores = {}

    if request.method == "POST":
        if bloqueo:
            messages.error(request, bloqueo)
        else:
            filas, valores, errores = _leer_planilla(request.POST, fecha)

            if errores:
                messages.error(
                    request,
                    "Corregí las filas marcadas. No se guardó ninguna.",
                )
            else:
                try:
                    token = _asegurar_sesion_edicion(request)
                    registros = guardar_planilla(
                        usuario=request.user,
                        token=token,
                        fecha=fecha,
                        filas=filas,
                        motivo=request.POST.get("motivo", ""),
                    )
                except PlanillaConErrores as exc:
                    errores = exc.errores
                    messages.error(
                        request,
                        "Corregí las filas marcadas. No se guardó ninguna.",
                    )
                except (ValidationError, PermissionDenied) as exc:
                    messages.error(request, _mensaje_error(exc))
                else:
                    messages.success(
                        request,
                        f"Se registraron {len(registros)} asistencias.",
                    )
                    return redirect(
                        f"{reverse('asistencia:registro_diario')}"
                        f"?fecha={fecha.isoformat()}"
                    )

    filas = _armar_filas(fecha, texto, valores, errores)
    marcadas = sum(1 for fila in filas if fila["registro"])

    return render(
        request,
        "asistencias/planilla_rapida.html",
        {
            "fecha": fecha,
            "fecha_texto": fecha.isoformat(),
            "texto": texto,
            "filas": filas,
            "marcas": MarcaAsistencia.vigentes(),
            "marca_presente": MarcaAsistencia.vigentes()
            .filter(codigo="P")
            .first(),
            "bloqueo": bloqueo,
            "jornada_cerrada": jornada_cerrada,
            "total": len(filas),
            "marcadas": marcadas,
            "pendientes": len(filas) - marcadas,
        },
    )
