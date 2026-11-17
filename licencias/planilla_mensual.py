"""
Procesamiento mensual: genera los cuadros IL-01 / IL-02 a partir de la
asistencia diaria (RF-12 a RF-16, RN-04, RN-05, RN-07, RN-08, RN-10, RN-11).

El circuito es el del Documento de Requerimientos v2.0:

1. En la diaria el personal asienta la marca (I, y luego LIC o P al recibir
   el formulario) en cada día del período.
2. `procesar_mes` detecta los días con novedad continua de cada agente,
   busca qué materias y horas tenía en ese intervalo según su horario
   semanal y genera un renglón independiente por cada materia afectada, con
   Desde y Hasta iguales al inicio y fin del período continuo.
3. En la interfaz mensual se elige el Artículo: el código de licencia se
   autocompleta y el renglón queda en IL-01 o IL-02.
4. `emitir_disposiciones_planilla` numera las disposiciones internas: una
   sola por agente y período, correlativas y en orden alfabético.

Este módulo no importa `asistencias` ni `reportes` a nivel de módulo para no
generar importaciones circulares.
"""
import calendar
import unicodedata
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from .clasificacion import (
    CategoriaSinPlanillaError,
    PLANILLA_IL01,
    PLANILLA_IL02,
    planilla_para_categoria,
)
from .models import LicenciaArticulo, LicenciaOtorgada, RenglonMensual

# Marcas de la diaria que generan renglón mensual (RF-12: ausencia, permiso o
# licencia). PR (Presente) no genera nada.
MARCAS_CON_NOVEDAD = ('I', 'P', 'LIC', 'LT')

# Días de la semana con horario (personal.Horario.dia), lunes = 0.
DIA_HORARIO = {0: 'LUN', 1: 'MAR', 2: 'MIE', 3: 'JUE', 4: 'VIE'}

# Cuánto se mira fuera del mes para conocer el inicio y el fin reales de un
# período que empezó antes o termina después (RF-14).
DIAS_DE_MARGEN = 62

DISPOSICION_TIPO = 'Disposición'
PENDIENTE = ''


def planilla_del_renglon(marca, articulo):
    """
    Cuadro al que va el renglón (RF-15, RN-04, RN-05).

    - Con artículo imputado: lo decide el catálogo maestro (hojas 1-2 del PDF
      -> IL-01; hojas 3-6 -> IL-02), a través de la categoría del artículo.
    - Sin artículo: las inasistencias y los permisos van a IL-02 (RN-05) y el
      largo tratamiento, que es una licencia por enfermedad, a IL-01 (RN-04).
      Una licencia (LIC) sin artículo queda pendiente de imputar.
    """
    if articulo is not None:
        try:
            return planilla_para_categoria(articulo.categoria_informe)
        except CategoriaSinPlanillaError:
            return PENDIENTE

    if marca in ('I', 'P'):
        return PLANILLA_IL02
    if marca == 'LT':
        return PLANILLA_IL01
    return PENDIENTE


def _rango_del_mes(anio, mes):
    if not 1 <= mes <= 12:
        raise ValueError("El mes debe estar entre 1 y 12.")
    return date(anio, mes, 1), date(anio, mes, calendar.monthrange(anio, mes)[1])


def _vigente(designacion, fecha):
    return (
        designacion.desde <= fecha
        and (designacion.hasta is None or fecha <= designacion.hasta)
    )


def _horas_de_horario(designacion, fecha):
    """Horas cátedra de la designación ese día según su horario semanal (RF-13)."""
    dia = DIA_HORARIO.get(fecha.weekday())
    if dia is None or not _vigente(designacion, fecha):
        return Decimal('0')
    return Decimal(sum(
        horario.horas_catedra
        for horario in designacion.horarios.all()
        if horario.dia == dia
    ))


def _es_dia_de_clase(designaciones, fecha):
    """¿El agente tiene que dictar alguna materia ese día?"""
    con_horario = [d for d in designaciones if list(d.horarios.all())]
    if not con_horario:
        # Sin horarios cargados no se puede saber: cuenta todo día de semana.
        return fecha.weekday() < 5
    return any(_horas_de_horario(d, fecha) > 0 for d in con_horario)


def _clave_de_novedad(registro):
    """
    Dos días forman un mismo período si tienen la misma clave.

    RN-06: la inasistencia injustificada o falta simple se computa únicamente
    por el día en que ocurrió, así que cada una es su propio período (la
    fecha forma parte de la clave).
    """
    codigo = registro.marca.codigo
    if codigo == 'I' and registro.estado_justificacion == 'INJUSTIFICADA':
        return (codigo, None, registro.fecha)
    return (codigo, registro.licencia_id, None)


def _bloques(fechas, designaciones):
    """
    RF-14: agrupa las fechas con novedad en períodos continuos. Dos fechas
    son continuas si entre ellas el agente no tenía ningún día de clase (un
    fin de semana o un día en que no dicta no cortan el período).
    """
    bloques = []
    for fecha in sorted(fechas):
        if bloques:
            anterior = bloques[-1][-1]
            hueco = (
                anterior + timedelta(days=n)
                for n in range(1, (fecha - anterior).days)
            )
            if not any(_es_dia_de_clase(designaciones, dia) for dia in hueco):
                bloques[-1].append(fecha)
                continue
        bloques.append([fecha])
    return bloques


def _oficina_por_defecto():
    """RN-07: código de oficina de los parámetros del sistema (1452)."""
    from reportes.models import ParametroSistema
    return ParametroSistema.obtener().codigo_oficina


def calcular_renglones(anio, mes):
    """
    Calcula, sin guardar, los renglones del mes. Devuelve una lista de dicts
    con: designacion, marca, desde, hasta, dias, horas, licencia y
    nro_formulario.
    """
    from asistencias.models import RegistroAsistencia
    from personal.models import Designacion

    primer_dia, ultimo_dia = _rango_del_mes(anio, mes)

    personas = set(
        RegistroAsistencia.objects.filter(
            fecha__range=(primer_dia, ultimo_dia),
            marca__codigo__in=MARCAS_CON_NOVEDAD,
        ).values_list('designacion__persona_id', flat=True)
    )
    if not personas:
        return []

    # Todos los registros de esos agentes en el mes y un margen alrededor:
    # hacen falta los "presentes" (cortan un período) y los días de otros
    # meses (dan el Desde y el Hasta reales).
    registros = (
        RegistroAsistencia.objects.filter(
            designacion__persona_id__in=personas,
            fecha__range=(
                primer_dia - timedelta(days=DIAS_DE_MARGEN),
                ultimo_dia + timedelta(days=DIAS_DE_MARGEN),
            ),
        )
        .select_related('marca', 'licencia')
        .order_by('fecha', 'designacion_id')
    )
    por_persona = defaultdict(list)
    designacion_de = {}
    designaciones_por_persona = defaultdict(list)
    for designacion in (
        Designacion.objects.filter(persona_id__in=personas)
        .select_related('persona', 'cargo', 'espacio_curricular')
        .prefetch_related('horarios')
        .order_by('pk')
    ):
        designacion_de[designacion.pk] = designacion
        designaciones_por_persona[designacion.persona_id].append(designacion)
    for registro in registros:
        por_persona[designacion_de[registro.designacion_id].persona_id].append(registro)

    renglones = []

    for persona_id in sorted(personas):
        designaciones = designaciones_por_persona[persona_id]
        del_agente = por_persona[persona_id]

        # registro de cada (designación, fecha) y fechas de cada novedad
        registro_de = {(r.designacion_id, r.fecha): r for r in del_agente}
        fechas_por_clave = defaultdict(set)
        for registro in del_agente:
            if registro.marca.codigo in MARCAS_CON_NOVEDAD:
                fechas_por_clave[_clave_de_novedad(registro)].add(registro.fecha)

        for clave, fechas in fechas_por_clave.items():
            marca = clave[0]

            for bloque in _bloques(fechas, designaciones):
                del_mes = [f for f in bloque if primer_dia <= f <= ultimo_dia]
                if not del_mes:
                    continue

                # RF-12 / RN-10: un renglón por cada materia que el agente
                # debía dictar en esos días, la haya cargado o no el operador.
                for designacion in designaciones:
                    dias = 0
                    horas = Decimal('0')
                    licencia = None
                    formulario = ''

                    for fecha in del_mes:
                        registro = registro_de.get((designacion.pk, fecha))

                        if registro is not None and _clave_de_novedad(registro) != clave:
                            # Esa materia tiene otra novedad ese día (o estuvo
                            # presente): no pertenece a este período.
                            continue

                        del_horario = _horas_de_horario(designacion, fecha)

                        if registro is None and del_horario <= 0:
                            continue  # ese día no dictaba esta materia

                        dias += 1
                        # RF-13: horas del horario semanal; si la designación
                        # no tiene horario cargado, las asentadas en la diaria.
                        horas += del_horario if del_horario > 0 else (
                            registro.horas_inasistidas if registro else Decimal('0')
                        )
                        if registro is not None:
                            licencia = licencia or registro.licencia
                            formulario = formulario or registro.nro_formulario

                    if dias:
                        renglones.append({
                            'designacion': designacion,
                            'marca': marca,
                            'desde': bloque[0],
                            'hasta': bloque[-1],
                            'dias': dias,
                            'horas': horas,
                            'licencia': licencia,
                            'nro_formulario': formulario or (
                                (licencia.nro_formulario or '') if licencia else ''
                            ),
                        })

    return renglones


def _articulo_equivalente(articulo, designacion):
    """
    El catálogo tiene el mismo artículo repetido por situación de revista.
    Devuelve el que corresponde a la designación (o el mismo si no hay otro).
    """
    if articulo is None or not designacion.situacion_revista:
        return articulo
    situacion = designacion.get_situacion_revista_display()
    if (articulo.sit_rev or '').strip().lower() == situacion.lower():
        return articulo
    return LicenciaArticulo.objects.filter(
        articulo=articulo.articulo, sit_rev__iexact=situacion,
    ).first() or articulo


@transaction.atomic
def procesar_mes(anio, mes, usuario=None):
    """
    Genera o actualiza la planilla mensual. Se puede correr todas las veces
    que haga falta: conserva lo que el operador ya imputó (artículo,
    resolución, disposición) y actualiza días, horas y fechas.

    Devuelve {'creados', 'actualizados', 'eliminados', 'desactualizados'}.
    """
    calculados = calcular_renglones(anio, mes)
    oficina = _oficina_por_defecto()

    existentes = {
        (r.designacion_id, r.marca, r.desde, r.hasta): r
        for r in RenglonMensual.objects.select_for_update().filter(anio=anio, mes=mes)
    }
    sin_usar = dict(existentes)
    resumen = {'creados': 0, 'actualizados': 0, 'eliminados': 0, 'desactualizados': 0}

    for datos in calculados:
        designacion = datos['designacion']
        clave = (designacion.pk, datos['marca'], datos['desde'], datos['hasta'])
        renglon = sin_usar.pop(clave, None)

        if renglon is None:
            # El período pudo crecer o achicarse: se reutiliza el renglón de
            # la misma materia y marca que se superpone, para no perder lo
            # ya imputado.
            for otra_clave, candidato in list(sin_usar.items()):
                if (
                    otra_clave[0] == designacion.pk
                    and otra_clave[1] == datos['marca']
                    and candidato.desde <= datos['hasta']
                    and datos['desde'] <= candidato.hasta
                ):
                    renglon = sin_usar.pop(otra_clave)
                    break

        if renglon is None:
            renglon = RenglonMensual(
                anio=anio, mes=mes, designacion=designacion, marca=datos['marca'],
                oficina=oficina,       # RN-07
                anio_planilla=anio,    # RN-08
                creado_por=usuario,
            )
            licencia = datos['licencia']
            if licencia is not None:
                # La licencia ya otorgada trae su artículo y su disposición.
                renglon.imputar(licencia.articulo)
                renglon.disp_tipo = licencia.disp_tipo or ''
                renglon.disp_numero = licencia.disp_numero or ''
                renglon.disp_anio = licencia.disp_anio
            else:
                renglon.planilla = planilla_del_renglon(datos['marca'], None)
            resumen['creados'] += 1
        else:
            resumen['actualizados'] += 1

        renglon.desde = datos['desde']
        renglon.hasta = datos['hasta']
        renglon.dias = datos['dias']
        renglon.horas = datos['horas']
        renglon.licencia = datos['licencia']
        renglon.nro_formulario = datos['nro_formulario']
        renglon.desactualizado = False
        renglon.actualizado_por = usuario
        renglon.save()

    # Renglones que la diaria ya no respalda (se corrigió una marca).
    for renglon in sin_usar.values():
        if renglon.disp_numero:
            # INC-02: con disposición emitida no se borra solo; se avisa.
            renglon.desactualizado = True
            renglon.actualizado_por = usuario
            renglon.save(update_fields=['desactualizado', 'actualizado_por', 'actualizado_en'])
            resumen['desactualizados'] += 1
        else:
            renglon.delete()
            resumen['eliminados'] += 1

    return resumen


def renglones_del_mes(anio, mes):
    return (
        RenglonMensual.objects.filter(anio=anio, mes=mes)
        .select_related(
            'designacion__persona', 'designacion__cargo',
            'designacion__espacio_curricular__carrera', 'articulo',
        )
        .order_by('designacion__persona__apellido_nombre', 'desde', 'designacion_id')
    )


def falta_formulario(renglon):
    """
    RF-09: una inasistencia (I) sin número de formulario todavía no tiene el
    papel que la justifica, así que no admite artículo de licencia. Primero
    se recibe el formulario en Recepción (que pasa la I a LIC, LT o P).
    """
    return renglon.marca == 'I' and not renglon.nro_formulario


def faltas_sin_formulario(anio, mes):
    """
    Bandeja de pendientes de la planilla mensual: inasistencias del mes que
    todavía esperan el papel, agrupadas por docente y día (un papel cubre
    todas las materias de ese día). Cada grupo trae el registro diario de la
    primera materia, que es el que abre Recepción de formularios.
    """
    from asistencias.models import RegistroAsistencia

    grupos = {}
    for renglon in renglones_del_mes(anio, mes):
        if not falta_formulario(renglon):
            continue
        clave = (renglon.designacion.persona_id, renglon.desde)
        grupos.setdefault(clave, []).append(renglon)

    pendientes = []
    for (persona_id, fecha), renglones in grupos.items():
        registro = (
            RegistroAsistencia.objects.filter(
                designacion__in=[r.designacion_id for r in renglones],
                fecha=fecha,
                marca__codigo='I',
            )
            .order_by('designacion_id')
            .first()
        )
        pendientes.append({
            'docente': renglones[0].designacion.persona,
            'fecha': fecha,
            'renglones': renglones,
            'registro': registro,
        })

    pendientes.sort(key=lambda p: (_clave_alfabetica(p['docente'].apellido_nombre), p['fecha']))
    return pendientes


def articulos_para_renglon(renglon, todos):
    """Artículos del catálogo que corresponden a la situación de revista."""
    situacion = (
        renglon.designacion.get_situacion_revista_display().lower()
        if renglon.designacion.situacion_revista else ''
    )
    propios = [a for a in todos if (a.sit_rev or '').strip().lower() == situacion]
    return propios or list(todos)


@transaction.atomic
def imputar_renglones(anio, mes, datos, usuario=None):
    """
    RF-15 / RF-16: guarda lo cargado en la interfaz mensual. `datos` es
    {id_renglon: {'articulo': id|'' , 'resolucion': str, 'oficina': str,
    'anio': str}}. Devuelve la cantidad de renglones modificados.

    Al elegir el artículo se autocompleta el código y se deriva el cuadro. Si
    en un mismo período (mismo agente, Desde y Hasta) se imputó una materia y
    otra quedó sin artículo, se le aplica el mismo artículo.
    """
    renglones = {
        r.pk: r for r in renglones_del_mes(anio, mes).select_for_update()
    }
    articulos = {a.pk: a for a in LicenciaArticulo.objects.all()}
    modificados = set()
    elegido_en_bloque = {}

    for pk, valores in datos.items():
        renglon = renglones.get(pk)
        if renglon is None:
            continue

        if 'articulo' in valores:
            texto = str(valores['articulo'] or '').strip()
            articulo = articulos.get(int(texto)) if texto.isdigit() else None
            if texto and articulo is None:
                raise ValidationError("El artículo elegido no existe en el catálogo.")
            # Solo se controla el artículo que el operador CAMBIA en esta
            # pantalla. Un renglón que no se tocó conserva lo que ya tenía
            # (por ejemplo, el artículo heredado de una licencia otorgada).
            cambia = (articulo.pk if articulo else None) != renglon.articulo_id
            if articulo is not None and cambia:
                if falta_formulario(renglon):
                    raise ValidationError(
                        f"{renglon.designacion.persona.apellido_nombre} tiene una "
                        f"inasistencia sin formulario el {renglon.desde:%d/%m/%Y}: "
                        "primero registrá el papel (en Recepción de formularios o "
                        "cargando la licencia en Nueva licencia) y después elegí "
                        "el artículo."
                    )
                situacion = renglon.designacion.situacion_revista and (
                    renglon.designacion.get_situacion_revista_display().lower()
                )
                del_articulo = (articulo.sit_rev or '').strip().lower()
                if situacion and del_articulo and situacion != del_articulo:
                    raise ValidationError(
                        f"El artículo {articulo.articulo} corresponde al personal "
                        f"{del_articulo} y {renglon.designacion.persona.apellido_nombre} "
                        f"revista como {situacion} en esa materia."
                    )
            if articulo is not None:
                elegido_en_bloque.setdefault(renglon.clave_de_bloque, articulo)
            if cambia:
                renglon.imputar(articulo)
                modificados.add(pk)

        resolucion = str(valores.get('resolucion', renglon.resolucion) or '').strip()[:100]
        oficina = str(valores.get('oficina', renglon.oficina) or '').strip()[:10]
        anio_texto = str(valores.get('anio', renglon.anio_planilla) or '').strip()

        if not oficina:
            oficina = _oficina_por_defecto()          # RN-07
        if anio_texto.isdigit() and 2000 <= int(anio_texto) <= 2100:
            anio_planilla = int(anio_texto)
        else:
            anio_planilla = anio                      # RN-08

        if (resolucion, oficina, anio_planilla) != (
            renglon.resolucion, renglon.oficina, renglon.anio_planilla
        ):
            renglon.resolucion = resolucion
            renglon.oficina = oficina
            renglon.anio_planilla = anio_planilla
            modificados.add(pk)

    # Mismo período, misma causa: las materias sin artículo toman el elegido.
    for pk, renglon in renglones.items():
        articulo = elegido_en_bloque.get(renglon.clave_de_bloque)
        if (
            articulo is not None
            and renglon.articulo_id is None
            and not falta_formulario(renglon)
        ):
            renglon.imputar(_articulo_equivalente(articulo, renglon.designacion))
            modificados.add(pk)

    for pk in modificados:
        renglon = renglones[pk]
        renglon.actualizado_por = usuario
        renglon.save()

    return len(modificados)


# ───────────── Disposiciones internas (RF-16, RN-11) ─────────────

def _clave_alfabetica(texto):
    descompuesto = unicodedata.normalize('NFKD', texto)
    return ''.join(c for c in descompuesto if not unicodedata.combining(c)).casefold()


def ultimo_numero_emitido(oficina, anio):
    """Mayor número de disposición usado en esa oficina y año (0 si no hay)."""
    mayor = 0
    numeros = list(
        LicenciaOtorgada.objects.filter(disp_oficina=oficina, disp_anio=anio)
        .values_list('disp_numero', flat=True)
    ) + list(
        RenglonMensual.objects.filter(oficina=oficina, disp_anio=anio)
        .values_list('disp_numero', flat=True)
    )
    for numero in numeros:
        if numero and numero.isdigit():
            mayor = max(mayor, int(numero))
    return mayor


def _lleva_disposicion(renglon):
    """
    Se emite disposición por cada formulario recibido: las marcas LIC, LT y P
    se asientan justamente al recibirlo (RF-09); una inasistencia solo si
    tiene número de formulario.
    """
    return renglon.marca in ('LIC', 'LT', 'P') or bool(renglon.nro_formulario)


def _bloques_a_numerar(anio, mes):
    """
    Períodos del mes que todavía no tienen disposición, en orden alfabético
    por apellido (RF-16). Devuelve [(clave, [renglones])].
    """
    bloques = defaultdict(list)
    for renglon in renglones_del_mes(anio, mes):
        if not renglon.disp_numero and _lleva_disposicion(renglon):
            bloques[renglon.clave_de_bloque].append(renglon)

    def orden(item):
        (persona_id, desde, hasta), renglones = item
        apellido = renglones[0].designacion.persona.apellido_nombre
        return (_clave_alfabetica(apellido), desde, hasta, persona_id)

    return sorted(bloques.items(), key=orden)


def disposiciones_emitidas_del_mes(anio, mes):
    """
    Disposiciones ya emitidas en los renglones del mes, agrupadas por número
    (RN-11): cada una con su docente, período y las materias que abarca.
    Devuelve una lista ordenada por año y número.
    """
    grupos = {}
    for renglon in renglones_del_mes(anio, mes):
        if not renglon.disp_numero:
            continue
        clave = (renglon.disp_anio or 0, renglon.disp_numero)
        grupos.setdefault(clave, []).append(renglon)

    def orden(clave):
        anio_disp, numero = clave
        return (anio_disp, int(numero) if numero.isdigit() else 0, numero)

    return [
        {
            'numero': numero,
            'anio': anio_disp or None,
            'renglones': grupos[(anio_disp, numero)],
        }
        for anio_disp, numero in sorted(grupos, key=orden)
    ]


def previsualizar_disposiciones_planilla(anio, mes):
    """[(numero, [renglones])] con los números que se asignarían."""
    numero = ultimo_numero_emitido(_oficina_por_defecto(), anio)
    resultado = []
    for _, renglones in _bloques_a_numerar(anio, mes):
        numero += 1
        resultado.append((numero, renglones))
    return resultado


@transaction.atomic
def emitir_disposiciones_planilla(anio, mes, usuario=None):
    """
    RF-16: numera las disposiciones internas del mes.

    - RN-11: un único número para todas las materias de un agente en un
      mismo día o período de licencia.
    - Correlativas, continuando el último número de la oficina y el año, con
      los períodos ordenados alfabéticamente por apellido del docente.
    - RN-07 / RN-08: oficina de los parámetros (1452) y año del período.

    Devuelve [(numero, [renglones])].
    """
    oficina = _oficina_por_defecto()
    numero = ultimo_numero_emitido(oficina, anio)
    emitidas = []

    for _, renglones in _bloques_a_numerar(anio, mes):
        numero += 1
        for renglon in renglones:
            renglon.disp_tipo = DISPOSICION_TIPO
            renglon.disp_numero = str(numero)
            renglon.disp_anio = anio
            renglon.oficina = renglon.oficina or oficina
            renglon.actualizado_por = usuario
            renglon.save()
        emitidas.append((numero, renglones))

    return emitidas


# ───────────── Cuadros para la pantalla y la exportación ─────────────

TITULOS = {
    PLANILLA_IL01: 'Cuadro IL-01 · Licencias por enfermedad',
    PLANILLA_IL02: 'Cuadro IL-02 · Inasistencias, permisos y otras causales',
    PENDIENTE: 'Pendientes de imputar · elija el artículo para ubicarlos en IL-01 o IL-02',
}


def cuadros_del_mes(anio, mes):
    """Renglones del mes separados por cuadro, en el orden IL-01, IL-02, pendientes."""
    renglones = list(renglones_del_mes(anio, mes))
    cuadros = []
    for planilla in (PLANILLA_IL01, PLANILLA_IL02, PENDIENTE):
        filas = [r for r in renglones if r.planilla == planilla]
        cuadros.append({
            'planilla': planilla or 'PENDIENTE',
            'titulo': TITULOS[planilla],
            'filas': filas,
            'total_horas': sum((r.horas for r in filas), Decimal('0')),
        })
    return cuadros
