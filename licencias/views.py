import csv
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.dateparse import parse_date
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from asistencias.services import (
    marcar_licencia,
    motivo_dia_no_laborable,
    registros_huerfanos_de_licencia,
)

from .dias import fecha_de_hoy, mes_vecino
from .forms import FiltroLicenciasForm, LicenciaOtorgadaForm, ResolucionAdjuntaForm
from .models import LicenciaArticulo, LicenciaOtorgada, ResolucionAdjunta
from .planilla_mensual import (
    articulos_para_renglon,
    cuadros_del_mes,
    emitir_disposiciones_planilla,
    disposiciones_emitidas_del_mes,
    faltas_sin_formulario,
    imputar_renglones,
    previsualizar_disposiciones_planilla,
    procesar_mes,
)
@login_required
@permission_required("licencias.view_licenciaotorgada", raise_exception=True)
def reporte_mensual_licencias(request, anio: int, mes: int):
    """
    El reporte por licencias fue reemplazado por la planilla mensual IL-01 /
    IL-02, que se arma desde la asistencia diaria (RF-12 a RF-16). La
    dirección se conserva para que los enlaces guardados no den error.
    """
    messages.info(
        request,
        "El reporte por licencias se reemplazó por la planilla mensual IL-01 / IL-02.",
    )
    return redirect("licencias:planilla_mensual", anio, mes)


def _marcar_y_avisar(request, licencia):
    """
    RN-07 / RF-14: marca en asistencias los días hábiles de la licencia y
    le informa al operador cómo quedó.
    """
    resumen = marcar_licencia(licencia, usuario=request.user)

    cantidad = len(resumen["marcados"])
    if cantidad:
        verbo = "Se marcó" if cantidad == 1 else "Se marcaron"
        dias = "día" if cantidad == 1 else "días"
        messages.info(request, f"{verbo} {cantidad} {dias} en asistencias.")

    # Fines de semana y feriados no se avisan: es lo esperado y haría ruido
    # en cada licencia que cruce un fin de semana.
    sin_marcar = [
        f"{fecha:%d/%m/%Y}: {motivo}"
        for fecha, motivo in resumen["omitidos"]
        if not motivo_dia_no_laborable(fecha)
    ]
    if sin_marcar:
        messages.warning(
            request,
            "No se marcaron en asistencias: " + "; ".join(sin_marcar) + ".",
        )

    for advertencia in resumen["advertencias"]:
        messages.warning(request, advertencia)

    # Dias que quedaron marcados como licencia pero ya no estan cubiertos
    # (por ejemplo, despues de acortar las fechas). No se corrigen solos:
    # el operador los ajusta a mano desde la carga diaria.
    huerfanos = registros_huerfanos_de_licencia(licencia)
    if huerfanos:
        fechas = ", ".join(f"{registro.fecha:%d/%m/%Y}" for registro in huerfanos)
        messages.warning(
            request,
            "Estos días quedaron marcados como licencia pero ya no están "
            f"cubiertos por ella: {fechas}. Corregilos desde la carga diaria "
            "de asistencias.",
        )

def _volver_seguro(request):
    """
    Dirección a la que volver después de guardar (por ejemplo, la planilla
    mensual). Solo se aceptan direcciones de este mismo sitio.
    """
    destino = request.POST.get("volver") or request.GET.get("volver") or ""
    if destino and url_has_allowed_host_and_scheme(
        destino, allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return destino
    return ""


@login_required 
@permission_required("licencias.add_licenciaotorgada", raise_exception=True)
@require_http_methods(["GET", "POST"])
def nueva_licencia_otorgada(request):
    volver = _volver_seguro(request)

    if request.method == "POST":
        form = LicenciaOtorgadaForm(request.POST)

        if form.is_valid():
            licencia = form.save()
            messages.success(
                request,
                "La licencia se registró correctamente."
            )
            _marcar_y_avisar(request, licencia)
            return redirect(volver or reverse("licencias:nueva_licencia_otorgada"))

    else:
        # Desde el cuadro de faltas sin formulario de la planilla mensual se
        # llega con la designación y la fecha ya elegidas. Solo precarga los
        # campos: el guardado es el mismo de siempre.
        inicial = {}
        designacion = request.GET.get("designacion", "")
        if designacion.isdigit():
            inicial["designacion"] = int(designacion)
        desde = parse_date(request.GET.get("desde", "") or "")
        if desde:
            inicial["desde"] = desde
            inicial["hasta"] = desde
        form = LicenciaOtorgadaForm(initial=inicial)

    return render(
        request,
        "licencias/nueva_licencia_otorgada.html",
        {"form": form, "volver": volver}
    )

LICENCIAS_POR_PAGINA = 20
@login_required
@permission_required("licencias.view_licenciaotorgada", raise_exception=True)
def listado_licencias_otorgadas(request):
    licencias = LicenciaOtorgada.objects.select_related(
        "designacion__persona",
        "designacion__cargo",
        "articulo",
    ).order_by("-desde", "-id")

    filtros = FiltroLicenciasForm(request.GET)
    filtros.is_valid()
    # Si algún parámetro es inválido, queda fuera de cleaned_data y se ignora.
    datos = filtros.cleaned_data

    if filtros.errors:
        messages.warning(
            request,
            "Algunos filtros no son válidos y se ignoraron.",
        )

    docente = (datos.get("docente") or "").strip()

    if docente:
        licencias = licencias.filter(
            Q(designacion__persona__apellido_nombre__icontains=docente)
        )

    articulo = datos.get("articulo")

    if articulo:
        licencias = licencias.filter(articulo=articulo)

    fecha_desde = datos.get("fecha_desde")
    fecha_hasta = datos.get("fecha_hasta")

    if fecha_desde:
        licencias = licencias.filter(
            Q(hasta__isnull=True) | Q(hasta__gte=fecha_desde)
        )

    if fecha_hasta:
        licencias = licencias.filter(desde__lte=fecha_hasta)


    articulos = LicenciaArticulo.objects.all().order_by("articulo")

    # Se muestran de a LICENCIAS_POR_PAGINA. get_page() tolera un número
    # inválido (va a la primera) o fuera de rango (va a la última).
    paginador = Paginator(licencias, LICENCIAS_POR_PAGINA)
    pagina = paginador.get_page(request.GET.get("page"))

    # Filtros actuales sin "page", para armar los enlaces de paginación.
    parametros = request.GET.copy()
    parametros.pop("page", None)

    return render(
        request,
        "licencias/listado_licencias_otorgadas.html",
        {
            "licencias": pagina,
            "articulos": articulos,
            "querystring": parametros.urlencode(),
        },
    )

@login_required
@permission_required("licencias.change_licenciaotorgada", raise_exception=True)
@require_http_methods(["GET", "POST"])
def editar_licencia_otorgada(request, licencia_id):
    licencia = get_object_or_404(LicenciaOtorgada, pk=licencia_id)

    if request.method == "POST":
        form = LicenciaOtorgadaForm(
            request.POST,
            instance=licencia,
        )

        if form.is_valid():
            licencia = form.save()
            messages.success(
                request,
                "La licencia se actualizó correctamente."
            )
            _marcar_y_avisar(request, licencia)

            url_listado = reverse("licencias:listado_licencias_otorgadas")
            filtros = request.GET.urlencode()

            if filtros:
                url_listado = f"{url_listado}?{filtros}"

            return redirect(url_listado)

        messages.error(request, "Revise los datos de la licencia.")

    else:
        form = LicenciaOtorgadaForm(instance=licencia)

    return render(
        request,
        "licencias/editar_licencia_otorgada.html",
        {
            "form": form,
            "licencia": licencia,
        },
    ) 

MESES = [
    (1, "Enero"), (2, "Febrero"), (3, "Marzo"), (4, "Abril"),
    (5, "Mayo"), (6, "Junio"), (7, "Julio"), (8, "Agosto"),
    (9, "Septiembre"), (10, "Octubre"), (11, "Noviembre"), (12, "Diciembre"),
]


@login_required
@permission_required("licencias.change_licenciaotorgada", raise_exception=True)
def generador_disposiciones(request):
    """
    Las disposiciones se emiten desde la planilla mensual (un solo lugar, para
    que una misma licencia no reciba dos números). La dirección se conserva
    para que los enlaces guardados no den error.
    """
    hoy = fecha_de_hoy()
    try:
        anio = int(request.GET.get("anio", hoy.year))
        mes = int(request.GET.get("mes", hoy.month))
    except ValueError:
        anio, mes = hoy.year, hoy.month
    if not (1 <= mes <= 12 and 2000 <= anio <= 2100):
        anio, mes = hoy.year, hoy.month
    messages.info(
        request,
        "Las disposiciones se emiten desde la planilla mensual IL-01 / IL-02.",
    )
    return redirect("licencias:planilla_mensual", anio, mes)


@login_required
@permission_required("licencias.change_licenciaotorgada", raise_exception=True)
@require_http_methods(["GET", "POST"])
def resoluciones_licencia(request, licencia_id):
    """RF-16: lista las resoluciones de una licencia y permite adjuntar otra."""
    licencia = get_object_or_404(
        LicenciaOtorgada.objects.select_related("designacion__persona", "articulo"),
        pk=licencia_id,
    )

    if request.method == "POST":
        form = ResolucionAdjuntaForm(request.POST, request.FILES)
        if form.is_valid():
            resolucion = form.save(commit=False)
            resolucion.licencia = licencia
            resolucion.save()
            messages.success(request, "La resolución se adjuntó correctamente.")
            return redirect("licencias:resoluciones_licencia", licencia_id=licencia.pk)
        messages.error(request, "Revise los datos de la resolución.")
    else:
        form = ResolucionAdjuntaForm()

    return render(request, "licencias/resoluciones_licencia.html", {
        "licencia": licencia,
        "resoluciones": licencia.resoluciones.all(),
        "form": form,
    })


@login_required
@permission_required("licencias.view_licenciaotorgada", raise_exception=True)
def descargar_resolucion(request, resolucion_id):
    """RF-16: entrega el PDF solo a quien tiene permiso (nunca por URL pública)."""
    resolucion = get_object_or_404(ResolucionAdjunta, pk=resolucion_id)
    return FileResponse(
        resolucion.archivo.open("rb"),
        as_attachment=True,
        filename=os.path.basename(resolucion.archivo.name),
        content_type="application/pdf",
    )


# ───────────── Planilla mensual IL-01 / IL-02 desde la diaria ─────────────

def _periodo_valido(anio, mes):
    if not 1 <= mes <= 12:
        raise Http404("Mes inválido")
    if not 2000 <= anio <= 2100:
        raise Http404("Año fuera de rango")


@login_required
@permission_required("licencias.view_licenciaotorgada", raise_exception=True)
@require_http_methods(["GET", "POST"])
def planilla_mensual(request, anio: int, mes: int):
    """
    Interfaz mensual (RF-12 a RF-16). Tres acciones, todas por POST:

    - procesar: genera o actualiza los renglones desde la asistencia diaria.
    - guardar:  imputa artículos (autocompleta código y cuadro), oficina,
                año y resolución.
    - emitir:   numera las disposiciones internas del mes.
    """
    _periodo_valido(anio, mes)
    url = reverse("licencias:planilla_mensual", args=[anio, mes])

    if request.method == "POST":
        if not request.user.has_perm("licencias.change_licenciaotorgada"):
            messages.error(request, "No tenés permiso para modificar la planilla mensual.")
            return redirect(url)

        accion = request.POST.get("accion")

        if accion == "procesar":
            resumen = procesar_mes(anio, mes, usuario=request.user)
            _registrar_en_bitacora(
                request.user, "Procesamiento de la planilla mensual",
                {"anio": anio, "mes": mes, **resumen},
            )
            messages.success(
                request,
                f"Mes procesado: {resumen['creados']} renglones nuevos, "
                f"{resumen['actualizados']} actualizados y "
                f"{resumen['eliminados']} eliminados.",
            )
            if resumen["desactualizados"]:
                messages.warning(
                    request,
                    f"{resumen['desactualizados']} renglones con disposición emitida "
                    "ya no coinciden con la asistencia diaria: revisalos a mano.",
                )

        elif accion == "guardar":
            datos = {}
            for clave, valor in request.POST.items():
                campo, _, pk = clave.rpartition("-")
                if campo in ("articulo", "resolucion", "oficina", "anio") and pk.isdigit():
                    datos.setdefault(int(pk), {})[campo] = valor
            try:
                cantidad = imputar_renglones(anio, mes, datos, usuario=request.user)
            except ValidationError as error:
                messages.error(request, " ".join(error.messages))
            else:
                messages.success(request, f"Se guardaron {cantidad} renglones.")

        elif accion == "emitir":
            emitidas = emitir_disposiciones_planilla(anio, mes, usuario=request.user)
            if emitidas:
                _registrar_en_bitacora(
                    request.user, "Emisión de disposiciones de la planilla mensual",
                    {"anio": anio, "mes": mes, "disposiciones": [n for n, _ in emitidas]},
                )
                messages.success(
                    request,
                    f"Se emitieron {len(emitidas)} disposiciones "
                    f"(N° {emitidas[0][0]} a {emitidas[-1][0]}).",
                )
            else:
                messages.info(request, "No había disposiciones para emitir en este mes.")

        return redirect(url)

    cuadros = cuadros_del_mes(anio, mes)
    articulos = list(LicenciaArticulo.objects.order_by("articulo", "sit_rev"))
    for cuadro in cuadros:
        for renglon in cuadro["filas"]:
            renglon.articulos = articulos_para_renglon(renglon, articulos)

    anio_anterior, mes_anterior = mes_vecino(anio, mes, -1)
    anio_siguiente, mes_siguiente = mes_vecino(anio, mes, 1)
    hay_renglones = any(cuadro["filas"] for cuadro in cuadros)

    return render(request, "licencias/planilla_mensual.html", {
        "anio": anio,
        "mes": mes,
        "nombre_mes": dict(MESES)[mes],
        "cuadros": cuadros,
        "hay_renglones": hay_renglones,
        "por_emitir": previsualizar_disposiciones_planilla(anio, mes),
        "emitidas": disposiciones_emitidas_del_mes(anio, mes),
        "sin_formulario": faltas_sin_formulario(anio, mes),
        "puede_modificar": request.user.has_perm("licencias.change_licenciaotorgada"),
        "mes_anterior": {"anio": anio_anterior, "mes": mes_anterior},
        "mes_siguiente": {"anio": anio_siguiente, "mes": mes_siguiente},
    })


def _registrar_en_bitacora(usuario, motivo, datos):
    """RF-20: el procesamiento y la emisión quedan en la bitácora única."""
    # Import local: reportes importa licencias, no al revés.
    from reportes.auditoria import AccionesReportes, registrar_evento
    registrar_evento(usuario, AccionesReportes.PLANILLA_MENSUAL, motivo=motivo, despues=datos)


ENCABEZADO_PLANILLA = [
    "Cuadro", "N° disposición", "Año disp.", "Resolución", "Oficina", "Año",
    "DNI", "Apellido y nombre", "Materia / cargo", "Sit. de revista", "Marca",
    "Artículo", "Cód. licencia", "Desde", "Hasta", "Días", "Horas",
]


def _texto_seguro(valor):
    """Evita que una planilla de cálculo interprete el texto como fórmula."""
    valor = "" if valor is None else str(valor)
    return "'" + valor if valor.startswith(("=", "+", "-", "@", "\t", "\r")) else valor


@login_required
@permission_required("licencias.view_licenciaotorgada", raise_exception=True)
def planilla_mensual_csv(request, anio: int, mes: int):
    """Exportación básica de los cuadros del mes (INC-01: datos básicos)."""
    _periodo_valido(anio, mes)

    respuesta = HttpResponse(content_type="text/csv; charset=utf-8")
    respuesta["Content-Disposition"] = (
        f'attachment; filename="planilla_mensual_{anio}_{mes:02d}.csv"'
    )
    respuesta.write("\ufeff")
    escritor = csv.writer(respuesta, delimiter=";")
    escritor.writerow(ENCABEZADO_PLANILLA)

    for cuadro in cuadros_del_mes(anio, mes):
        for r in cuadro["filas"]:
            designacion = r.designacion
            materia = (
                designacion.espacio_curricular.nombre
                if designacion.espacio_curricular else designacion.cargo.descripcion
            )
            escritor.writerow([
                cuadro["planilla"],
                r.disp_numero,
                r.disp_anio or "",
                _texto_seguro(r.resolucion),
                _texto_seguro(r.oficina),
                r.anio_planilla,
                _texto_seguro(designacion.persona.dni),
                _texto_seguro(designacion.persona.apellido_nombre),
                _texto_seguro(materia),
                designacion.situacion_revista,
                r.marca,
                _texto_seguro(r.articulo.articulo if r.articulo else ""),
                _texto_seguro(r.cod_licencia),
                r.desde.strftime("%d/%m/%Y"),
                r.hasta.strftime("%d/%m/%Y"),
                r.dias,
                r.horas,
            ])

    return respuesta
