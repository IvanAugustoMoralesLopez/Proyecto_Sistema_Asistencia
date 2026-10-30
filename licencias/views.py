import calendar
from datetime import date, timedelta

from django.http import Http404
from django.shortcuts import render

# Importá el modelo Horario desde la app donde esté definido
from personal.models import Horario

from .clasificacion import CategoriaSinPlanillaError
from .dias import obtener_feriados
from .models import LicenciaOtorgada
from .services import clasificar_planilla_licencia 
from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.shortcuts import redirect, reverse
from django.views.decorators.http import require_http_methods
from .forms import LicenciaOtorgadaForm

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


def reporte_mensual_licencias(request, anio: int, mes: int):
    if not 1 <= mes <= 12:
        raise Http404("Mes inválido")

    primer_dia = date(anio, mes, 1)
    ultimo_dia = date(anio, mes, calendar.monthrange(anio, mes)[1])

    # RF-10: los feriados/asuetos no generan horas afectadas. Una sola consulta.
    feriados = obtener_feriados(primer_dia, ultimo_dia)

    # RF-12: licencias que intersecan con este mes
    licencias = LicenciaOtorgada.objects.filter(
        desde__lte=ultimo_dia
    ).exclude(
        hasta__lt=primer_dia
    ).select_related('designacion', 'articulo')

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
            'espacio_curricular': lic.designacion.espacio_curricular_id,
            'licencia_solicitada': f"{lic.articulo.articulo} - {lic.articulo.tipo_licencia}",
            'planilla': planilla_destino,
            'requiere_revision': requiere_revision,
            'fecha_inicio': inicio_mes,
            'fecha_fin': fin_mes,
            'dias_totales': dias_totales_mes,
            'horas_descontadas': horas_afectadas,
        })

    return render(request, 'licencias/reporte_mensual.html', {
        'anio': anio,
        'mes': mes,
        'desglose': desglose,
        })
 
@permission_required("licencias.add_licenciaotorgada", raise_exception=True)
@require_http_methods(["GET", "POST"])
def nueva_licencia_otorgada(request):
    if request.method == "POST":
        form = LicenciaOtorgadaForm(request.POST)

        if form.is_valid():
            form.save()
            messages.success(
                request,
                "La licencia se registró correctamente."
            )
            return redirect(reverse("licencias:nueva_licencia_otorgada"))

        messages.error(request, "Revise los datos de la licencia.")

    else:
        form = LicenciaOtorgadaForm()

    return render(
        request,
        "licencias/nueva_licencia_otorgada.html",
        {"form": form}
    )
