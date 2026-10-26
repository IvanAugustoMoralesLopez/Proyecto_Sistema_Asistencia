from django.shortcuts import render
from datetime import date, timedelta
import calendar
from .models import LicenciaOtorgada
from .services import clasificar_planilla_licencia
# Importá el modelo Horario desde la app donde esté definido
from personal.models import Horario 

# Mapeo de Python weekday() a formato varchar(3) de la DB
MAPEO_DIAS = {
    0: 'LUN', 1: 'MAR', 2: 'MIE', 3: 'JUE', 4: 'VIE', 5: 'SAB', 6: 'DOM'
}

def reporte_mensual_licencias(request, anio: int, mes: int):
    primer_dia = date(anio, mes, 1)
    ultimo_dia = date(anio, mes, calendar.monthrange(anio, mes)[1])

    # RF-12: Traemos las licencias que intersecan con este mes
    licencias = LicenciaOtorgada.objects.filter(
        desde__lte=ultimo_dia
    ).exclude(
        hasta__lt=primer_dia
    ).select_related('designacion', 'articulo')

    desglose = []

    for lic in licencias:
        # RF-15: Clasificación IL-01 / IL-02
        planilla_destino = clasificar_planilla_licencia(lic) 
        
        inicio_mes = max(lic.desde, primer_dia)
        fin_mes = min(lic.hasta, ultimo_dia) if lic.hasta else ultimo_dia
        
        # Diccionario con el total de horas que dicta por día (ej: {'LUN': 4, 'MIE': 2})
        horarios = Horario.objects.filter(designacion=lic.designacion)
        horas_por_dia = {}
        for h in horarios:
            horas_por_dia[h.dia] = horas_por_dia.get(h.dia, 0) + h.horas_catedra
        
        horas_afectadas = 0
        dias_totales_mes = (fin_mes - inicio_mes).days + 1
        
        # RF-13: Iteramos los días de la licencia y sumamos las horas afectadas
        for i in range(dias_totales_mes):
            dia_evaluado = inicio_mes + timedelta(days=i)
            dia_str = MAPEO_DIAS[dia_evaluado.weekday()]
            
            if dia_str in horas_por_dia:
                horas_afectadas += horas_por_dia[dia_str]
        
        desglose.append({
            'dni_docente': lic.designacion.persona_id, 
            'espacio_curricular': lic.designacion.espacio_curricular_id,
            'licencia_solicitada': f"{lic.articulo.articulo} - {lic.articulo.tipo_licencia}",
            'planilla': planilla_destino,
            'fecha_inicio': inicio_mes,
            'fecha_fin': fin_mes,
            'dias_totales': dias_totales_mes,
            'horas_descontadas': horas_afectadas,
        })

    return render(request, 'licencias/reporte_mensual.html', {
        'anio': anio,
        'mes': mes,
        'desglose': desglose
    })