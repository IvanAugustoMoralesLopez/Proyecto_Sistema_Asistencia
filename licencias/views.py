import os
import calendar
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from personal.models import Horario

from asistencias.services import (
    inasistencias_del_periodo,
    marcar_licencia,
    motivo_dia_no_laborable,
    registros_huerfanos_de_licencia,
)

from .clasificacion import CategoriaSinPlanillaError, PLANILLA_IL01, PLANILLA_IL02
from .dias import fecha_de_hoy, mes_vecino, obtener_feriados
from .forms import FiltroLicenciasForm, LicenciaOtorgadaForm, ResolucionAdjuntaForm
from .models import LicenciaArticulo, LicenciaOtorgada, ResolucionAdjunta
from .services import (
    clasificar_planilla_licencia,
    emitir_disposiciones_mes,
    previsualizar_disposiciones_mes,
)
# Mapeo de Python weekday() a formato varchar(3) de la DB
MAPEO_DIAS = {
    0: 'LUN', 1: 'MAR', 2: 'MIE', 3: 'JUE', 4: 'VIE', 5: 'SAB', 6: 'DOM'
}

SIN_CLASIFICAR = 'SIN CLASIFICAR'


def _horas_por_dia(designacion_id, cache):
    """Horas cátedra por día de la semana de una designación (ej: {'LUN': 4})."""
    if designacion_id not in cache:
        horas = {}
        for h in Horario.objects.filter(designacion_id=designacion_id):
            horas[h.dia] = horas.get(h.dia, 0) + h.horas_catedra
        cache[designacion_id] = horas
    return cache[designacion_id]

@login_required
@permission_required("licencias.view_licenciaotorgada", raise_exception=True)
def reporte_mensual_licencias(request, anio: int, mes: int):
    if not 1 <= mes <= 12:
        raise Http404("Mes inválido")
    if not 2000 <= anio <= 2100:
        raise Http404("Año fuera de rango")

    primer_dia = date(anio, mes, 1)
    ultimo_dia = date(anio, mes, calendar.monthrange(anio, mes)[1])

    # RF-10: los feriados/asuetos no generan horas afectadas. Una sola consulta.
    feriados = obtener_feriados(primer_dia, ultimo_dia)

    # RF-12: licencias que intersecan con este mes
    licencias = LicenciaOtorgada.objects.filter(
        desde__lte=ultimo_dia
    ).exclude(
        hasta__lt=primer_dia
    ).select_related(
        'designacion__persona',
        'designacion__espacio_curricular',
        'designacion__cargo',
        'articulo',
    )

    desglose = []
    cache_horarios = {}

    for lic in licencias:
        # RF-15: clasificación IL-01 / IL-02 (estricta, RN-04 / RN-05)
        try:
            planilla_destino = clasificar_planilla_licencia(lic)
            requiere_revision = False
        except CategoriaSinPlanillaError:
            planilla_destino = SIN_CLASIFICAR
            requiere_revision = True

        inicio_mes = max(lic.desde, primer_dia)
        fin_mes = min(lic.hasta, ultimo_dia) if lic.hasta else ultimo_dia

        horas_por_dia = _horas_por_dia(lic.designacion_id, cache_horarios)

        horas_afectadas = 0
        dias_totales_mes = (fin_mes - inicio_mes).days + 1

        # RF-13: se recorren los días de la licencia y se suman las horas afectadas.
        # No se usa "solo días hábiles" porque pueden existir horarios en sábado;
        # lo único que se omite son los feriados (RF-10).
        for i in range(dias_totales_mes):
            dia_evaluado = inicio_mes + timedelta(days=i)
            if dia_evaluado in feriados:
                continue
            horas_afectadas += horas_por_dia.get(MAPEO_DIAS[dia_evaluado.weekday()], 0)

        desglose.append({
            'dni_docente': lic.designacion.persona_id,
            'docente': lic.designacion.persona.apellido_nombre,
            'espacio_curricular': (
                lic.designacion.espacio_curricular.nombre
                if lic.designacion.espacio_curricular
                else None
            ),
            'cargo': (
                lic.designacion.cargo.descripcion
                if lic.designacion.cargo_id
                else None
            ),
            'licencia_solicitada': f"{lic.articulo.articulo} - {lic.articulo.tipo_licencia}",
            'planilla': planilla_destino,
            'requiere_revision': requiere_revision,
            'fecha_inicio': inicio_mes,
            'fecha_fin': fin_mes,
            'dias_totales': dias_totales_mes,
            'horas_descontadas': horas_afectadas,
        })

    total_horas = sum(fila['horas_descontadas'] for fila in desglose)

    # Una tabla por planilla: IL-01, IL-02 y las que no se pudieron clasificar.
    grupos = []
    for planilla, titulo in (
        (PLANILLA_IL01, 'Licencias por salud (planilla IL-01): enfermedad, tratamiento y enfermedad familiar'),
        (PLANILLA_IL02, 'Licencias administrativas (planilla IL-02): razones particulares, exámenes, duelo, matrimonio y otras'),
        (SIN_CLASIFICAR, 'Sin clasificar (requieren revisión)'),
    ):
        filas = [fila for fila in desglose if fila['planilla'] == planilla]
        grupos.append({
            'planilla': planilla,
            'titulo': titulo,
            'filas': filas,
            'total_horas': sum(fila['horas_descontadas'] for fila in filas),
        })

    # RF-12: inasistencias del registro diario (marcas I y PR), una fila por
    # designacion. Las licencias (LIC y LT) ya estan contadas mas arriba.
    por_designacion = {}
    for registro in inasistencias_del_periodo(primer_dia, ultimo_dia):
        designacion = registro.designacion
        fila = por_designacion.get(designacion.pk)

        if fila is None:
            fila = por_designacion[designacion.pk] = {
                'dni_docente': designacion.persona_id,
                'docente': designacion.persona.apellido_nombre,
                'espacio_curricular': (
                    designacion.espacio_curricular.nombre
                    if designacion.espacio_curricular
                    else None
                ),
                'cargo': (
                    designacion.cargo.descripcion
                    if designacion.cargo_id
                    else None
                ),
                'dias': 0,
                'horas': 0,
            }

        fila['dias'] += 1
        fila['horas'] += registro.horas_inasistidas

    inasistencias = sorted(
        por_designacion.values(), key=lambda fila: fila['docente'],
    )
    total_horas_inasistencias = sum(fila['horas'] for fila in inasistencias)

    anio_anterior, mes_anterior = mes_vecino(anio, mes, -1)
    anio_siguiente, mes_siguiente = mes_vecino(anio, mes, 1)

    return render(request, 'licencias/reporte_mensual.html', {
        'anio': anio,
        'mes': mes,
        'desglose': desglose,
        'total_horas': total_horas,
        'grupos': grupos,
        'mes_anterior': {'anio': anio_anterior, 'mes': mes_anterior},
        'mes_siguiente': {'anio': anio_siguiente, 'mes': mes_siguiente},
        'inasistencias': inasistencias,
        'total_horas_inasistencias': total_horas_inasistencias,
    })


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

@login_required 
@permission_required("licencias.add_licenciaotorgada", raise_exception=True)
@require_http_methods(["GET", "POST"])
def nueva_licencia_otorgada(request):
    if request.method == "POST":
        form = LicenciaOtorgadaForm(request.POST)

        if form.is_valid():
            licencia = form.save()
            messages.success(
                request,
                "La licencia se registró correctamente."
            )
            _marcar_y_avisar(request, licencia)
            return redirect(reverse("licencias:nueva_licencia_otorgada"))

    else:
        form = LicenciaOtorgadaForm()

    return render(
        request,
        "licencias/nueva_licencia_otorgada.html",
        {"form": form}
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
@require_http_methods(["GET", "POST"])
def generador_disposiciones(request):
    """
    RF-16: pantalla del generador de disposiciones. GET muestra la vista previa
    del mes sin guardar nada; POST emite las disposiciones del mes.
    """
    datos = request.POST if request.method == "POST" else request.GET
    hoy = fecha_de_hoy()
    try:
        anio = int(datos.get("anio", hoy.year))
        mes = int(datos.get("mes", hoy.month))
    except ValueError:
        raise Http404("Año o mes inválido.")
    if not (1 <= mes <= 12 and 2000 <= anio <= 2100):
        raise Http404("Año o mes fuera de rango.")

    if request.method == "POST":
        resultado = emitir_disposiciones_mes(anio, mes)
        emitidas = len(resultado["emitidas"])
        omitidas = len(resultado["omitidas"])
        if emitidas:
            messages.success(
                request,
                f"Se emitieron {emitidas} disposiciones. "
                f"Licencias omitidas por no tener N° de formulario: {omitidas}.",
            )
        else:
            messages.info(request, "No había disposiciones para emitir en ese mes.")
        return redirect(
            f"{reverse('licencias:generador_disposiciones')}?anio={anio}&mes={mes}"
        )

    previa = previsualizar_disposiciones_mes(anio, mes)
    return render(request, "licencias/generador_disposiciones.html", {
        "anio": anio,
        "mes": mes,
        "meses": MESES,
        "a_emitir": previa["a_emitir"],
        "omitidas": previa["omitidas"],
        "oficina": previa["oficina"],
    }) 

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