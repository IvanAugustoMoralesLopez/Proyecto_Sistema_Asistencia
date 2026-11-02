import calendar
import unicodedata
from datetime import date

from django.db import transaction
from django.db.models import Q

from .clasificacion import planilla_para_categoria
from .dias import contar_dias_habiles, obtener_feriados, rango_en_anio
from .models import LicenciaOtorgada


def dias_usados_en_anio(dni: str, articulo: str, anio: int, excluir_id: int = None) -> int:
    """
    Días hábiles consumidos por el docente en `anio` para el artículo dado.

    `excluir_id`: id de una licencia que NO debe contarse. Se usa al editar,
    para que la licencia no se cuente contra sí misma. Por defecto no excluye
    nada, así que las llamadas existentes (reportes, etc.) siguen igual.
    """
    licencias = LicenciaOtorgada.objects.filter(
        designacion__persona__dni=dni,
        articulo__articulo=articulo,
        desde__year__lte=anio,
    ).filter(
        Q(hasta__isnull=True) | Q(hasta__year__gte=anio)
    )

    if excluir_id is not None:
        licencias = licencias.exclude(pk=excluir_id)

    # Una sola consulta de feriados para todo el año (antes era una por licencia).
    feriados = obtener_feriados(date(anio, 1, 1), date(anio, 12, 31))
    hoy = date.today()

    total_dias = 0
    for lic in licencias:
        rango = rango_en_anio(lic.desde, lic.hasta, anio, hoy)
        if rango is None:
            continue
        inicio, fin = rango
        total_dias += contar_dias_habiles(inicio, fin, feriados)

    return total_dias


def clasificar_planilla_licencia(licencia: LicenciaOtorgada) -> str:
    """
    Asigna la licencia a IL-01 (salud, RN-04) o IL-02 (administrativas, RN-05).
    Lanza CategoriaSinPlanillaError si la categoría del artículo no está
    contemplada en ninguna de las dos reglas.
    """
    return planilla_para_categoria(licencia.articulo.categoria_informe) 


DISPOSICION_TIPO = 'Disposición'


def _clave_alfabetica(licencia):
    """Clave de orden de RN-11: por apellido, sin distinguir tildes ni mayúsculas."""
    nombre = licencia.designacion.persona.apellido_nombre
    descompuesto = unicodedata.normalize('NFKD', nombre)
    sin_tildes = ''.join(c for c in descompuesto if not unicodedata.combining(c))
    return (sin_tildes.casefold(), licencia.desde, licencia.pk)


def _ultimo_numero_emitido(oficina, anio):
    """Mayor número de disposición ya usado en esa oficina y año (0 si no hay)."""
    mayor = 0
    numeros = LicenciaOtorgada.objects.filter(
        disp_oficina=oficina, disp_anio=anio,
    ).values_list('disp_numero', flat=True)
    for numero in numeros:
        if numero and numero.isdigit():
            mayor = max(mayor, int(numero))
    return mayor


def emitir_disposiciones_mes(anio: int, mes: int, oficina: str = None) -> dict:
    """
    Emite las Disposiciones Internas de las licencias que empiezan en el mes
    (RF-16). Devuelve {'emitidas': [(numero, licencia)], 'omitidas': [licencia]}.

    - RN-10: solo se emiten las licencias con N° de formulario en papel; las
      demás quedan en 'omitidas' y no se tocan.
    - RN-11: se ordenan alfabéticamente por apellido y se numeran en forma
      correlativa, continuando desde el último número de la oficina y el año.
    - Lo ya emitido (con disp_numero) no se vuelve a numerar.
    - `oficina` por defecto: la de ParametroSistema (RF-21).
    """
    if not 1 <= mes <= 12:
        raise ValueError("El mes debe estar entre 1 y 12.")

    if oficina is None:
        # Import local: reportes importa licencias, no al revés.
        from reportes.models import ParametroSistema
        oficina = ParametroSistema.obtener().codigo_oficina

    primer_dia = date(anio, mes, 1)
    ultimo_dia = date(anio, mes, calendar.monthrange(anio, mes)[1])

    pendientes = LicenciaOtorgada.objects.filter(
        desde__gte=primer_dia,
        desde__lte=ultimo_dia,
    ).filter(
        Q(disp_numero__isnull=True) | Q(disp_numero='')
    ).select_related('designacion__persona', 'articulo')

    emitibles, omitidas = [], []
    for licencia in pendientes:
        if (licencia.nro_formulario or '').strip():
            emitibles.append(licencia)
        else:
            omitidas.append(licencia)

    emitibles.sort(key=_clave_alfabetica)
    omitidas.sort(key=_clave_alfabetica)

    emitidas = []
    with transaction.atomic():
        numero = _ultimo_numero_emitido(oficina, anio)
        for licencia in emitibles:
            numero += 1
            licencia.disp_tipo = DISPOSICION_TIPO
            licencia.disp_oficina = oficina
            licencia.disp_numero = str(numero)
            licencia.disp_anio = anio
            licencia.save(update_fields=[
                'disp_tipo', 'disp_oficina', 'disp_numero', 'disp_anio',
            ])
            emitidas.append((numero, licencia))

    return {'emitidas': emitidas, 'omitidas': omitidas}
