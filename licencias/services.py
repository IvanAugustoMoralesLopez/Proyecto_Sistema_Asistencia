from datetime import date, timedelta
from django.db.models import Q
from .models import LicenciaOtorgada
from asistencias.models import DiaNoLaborable

def dias_usados_en_anio(dni: str, articulo: str, anio: int) -> int:
    licencias = LicenciaOtorgada.objects.filter(
        designacion__persona__dni=dni,
        articulo__articulo=articulo,
        desde__year__lte=anio
    ).filter(
        Q(hasta__isnull=True) | Q(hasta__year__gte=anio)
    )

    total_dias = 0
    hoy = date.today()

    for lic in licencias:
        # Recortamos el inicio al año evaluado
        inicio = max(lic.desde, date(anio, 1, 1))
        
        # FIX: Si no hay 'hasta', el tope es hoy (sin pasarse del 31 de dic de ese año)
        if lic.hasta:
            fin = min(lic.hasta, date(anio, 12, 31))
        else:
            fin = min(hoy, date(anio, 12, 31))
        
        # Obtenemos los feriados del rango en un formato optimizado (Set)
        feriados = set(DiaNoLaborable.objects.filter(
            fecha__range=[inicio, fin]
        ).values_list('fecha', flat=True))
        
        # Contamos solo días hábiles (lunes a viernes, no feriados)
        rango_dias = (fin - inicio).days + 1
        for i in range(rango_dias):
            dia_evaluado = inicio + timedelta(days=i)
            if dia_evaluado.weekday() < 5 and dia_evaluado not in feriados:
                total_dias += 1
                
    return total_dias

def clasificar_planilla_licencia(licencia: LicenciaOtorgada) -> str:
    """Evalúa la licencia y la asigna a IL-01 (Salud) o IL-02 (Administrativa)."""
    # RN-04: Licencias médicas y de salud van a IL-01
    categorias_salud = ['Enfermedad común', 'Largo tratamiento']
    if licencia.articulo.categoria_informe in categorias_salud:
        return 'IL-01'
    
    # RN-05: Razones particulares, permisos y otros van a IL-02
    return 'IL-02'