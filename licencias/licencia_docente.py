"""
Licencia por docente.

La licencia se pide UNA vez por docente: el sistema busca solo sus materias y
cargos afectados (las designaciones vigentes con clase en el período, según
el horario) y guarda una LicenciaOtorgada por cada una, todas con el mismo
grupo y la misma disposición (RN-11: una por agente y período).

La disposición se numera al guardar: se propone el próximo número libre de
la oficina y el año, y el operador lo puede cambiar. Si el número ya lo usa
otro pedido, no se guarda.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from personal.models import Designacion

from .models import LicenciaOtorgada, RenglonMensual


def _materia(designacion):
    if designacion.espacio_curricular_id:
        return designacion.espacio_curricular.nombre
    return designacion.cargo.descripcion


def designaciones_del_docente(persona, desde, hasta=None):
    """Designaciones activas del docente vigentes en algún día del período."""
    fin = hasta or desde
    return (
        Designacion.objects.select_related("persona", "cargo", "espacio_curricular")
        .prefetch_related("horarios")
        .filter(persona=persona, activo=True, desde__lte=fin)
        .filter(Q(hasta__isnull=True) | Q(hasta__gte=desde))
        .order_by("desde", "pk")
    )


def materias_afectadas(persona, desde, hasta=None):
    """
    Una entrada por designación del docente en el período, con los días en
    que tiene clase y las horas cátedra. Una licencia abierta (sin «hasta»)
    se calcula solo para el primer día.
    """
    from asistencias.services import horas_del_dia
    from asistencias.services.reglas import DIAS_HABILES

    fin = hasta or desde
    materias = []

    for designacion in designaciones_del_docente(persona, desde, hasta):
        inicio = max(desde, designacion.desde)
        tope = min(fin, designacion.hasta) if designacion.hasta else fin
        dias = []
        horas = Decimal("0")
        fecha = inicio

        while fecha <= tope:
            if fecha.weekday() in DIAS_HABILES:
                del_dia = horas_del_dia(designacion, fecha)
                if del_dia > 0:
                    dias.append(fecha)
                    horas += del_dia
            fecha += timedelta(days=1)

        materias.append(
            {
                "designacion": designacion,
                "materia": _materia(designacion),
                "situacion": designacion.get_situacion_revista_display()
                if designacion.situacion_revista
                else "",
                "dias": dias,
                "horas": horas,
            }
        )

    return materias


def proximo_numero(oficina, anio):
    from .planilla_mensual import ultimo_numero_emitido

    return ultimo_numero_emitido(oficina, anio) + 1


def quien_usa_el_numero(oficina, numero, anio, *, excluir_grupo=None, persona=None):
    """
    Descripción de quién ya usa ese número de disposición en la oficina y el
    año, o None si está libre. El propio pedido (`excluir_grupo`) no cuenta.
    """
    if not numero:
        return None

    licencias = LicenciaOtorgada.objects.select_related("designacion__persona").filter(
        disp_oficina=oficina, disp_numero=str(numero), disp_anio=anio
    )
    if excluir_grupo is not None:
        licencias = licencias.exclude(grupo=excluir_grupo)
    otra = licencias.first()
    if otra is not None:
        return (
            f"la licencia de {otra.designacion.persona.apellido_nombre} "
            f"del {otra.desde:%d/%m/%Y}"
        )

    renglones = RenglonMensual.objects.select_related("designacion__persona").filter(
        oficina=oficina, disp_numero=str(numero), disp_anio=anio
    )
    if excluir_grupo is not None:
        renglones = renglones.exclude(licencia__grupo=excluir_grupo)
    renglon = renglones.first()
    if renglon is not None:
        return (
            f"la planilla de {renglon.designacion.persona.apellido_nombre} "
            f"({renglon.mes:02d}/{renglon.anio})"
        )

    return None


def validar_numero_libre(oficina, numero, anio, *, excluir_grupo=None):
    usado = quien_usa_el_numero(oficina, numero, anio, excluir_grupo=excluir_grupo)
    if usado:
        raise ValidationError(
            f"La disposición N° {numero}/{anio} de la oficina {oficina} ya la "
            f"usa {usado}. Elegí otro número."
        )


@transaction.atomic
def crear_licencia_docente(
    *,
    persona,
    articulo,
    desde,
    hasta,
    designaciones,
    datos,
    disposicion,
):
    """
    Crea una LicenciaOtorgada por cada designación elegida, todas en el mismo
    grupo y con la misma disposición. Es todo o nada: si una materia no
    cumple las reglas (situación de revista, superposición, tope anual), no
    se guarda ninguna y el error dice cuál.

    `datos`: nro_formulario, justifica, resolucion_excepcion, observaciones.
    `disposicion`: tipo, oficina, numero, anio.
    """
    if not designaciones:
        raise ValidationError("Elegí al menos una materia o cargo afectado.")

    grupo = uuid.uuid4()
    numero = (disposicion.get("numero") or "").strip()
    oficina = (disposicion.get("oficina") or "").strip()
    anio = disposicion.get("anio")

    if numero:
        validar_numero_libre(oficina, numero, anio)

    creadas = []
    errores = []

    for designacion in designaciones:
        inicio = max(desde, designacion.desde)
        fin = hasta
        if designacion.hasta and (fin is None or designacion.hasta < fin):
            fin = designacion.hasta

        licencia = LicenciaOtorgada(
            designacion=designacion,
            articulo=articulo,
            sit_rev=(
                designacion.get_situacion_revista_display()
                if designacion.situacion_revista
                else (articulo.sit_rev or "")
            )[:20],
            desde=inicio,
            hasta=fin,
            grupo=grupo,
            disp_tipo=(disposicion.get("tipo") or "")[:20] or None,
            disp_oficina=oficina or None,
            disp_numero=numero or None,
            disp_anio=anio if numero else None,
            nro_formulario=(datos.get("nro_formulario") or "").strip()[:20],
            justifica=datos.get("justifica"),
            resolucion_excepcion=(datos.get("resolucion_excepcion") or "").strip(),
            observaciones=(datos.get("observaciones") or "").strip() or None,
        )

        try:
            licencia.full_clean()
        except ValidationError as exc:
            errores.append(f"{_materia(designacion)}: {' '.join(exc.messages)}")
            continue

        licencia.save()
        creadas.append(licencia)

    if errores:
        raise ValidationError(errores)

    return creadas


def licencias_del_grupo(licencia):
    """Todas las licencias del mismo pedido (la misma, si no tiene grupo)."""
    if licencia.grupo is None:
        return [licencia]
    return list(
        LicenciaOtorgada.objects.select_related(
            "designacion__persona",
            "designacion__cargo",
            "designacion__espacio_curricular",
            "articulo",
        )
        .filter(grupo=licencia.grupo)
        .order_by("designacion_id")
    )


@transaction.atomic
def prorrogar(licencias, nuevo_hasta):
    """
    Extiende todas las licencias del pedido hasta `nuevo_hasta` (sin pasar
    del fin de cada designación). Las validaciones del modelo (tope anual,
    superposición) se vuelven a controlar. Después hay que marcar la diaria.
    """
    for licencia in licencias:
        if licencia.hasta is not None and nuevo_hasta <= licencia.hasta:
            raise ValidationError(
                "La prórroga tiene que terminar después del "
                f"{licencia.hasta:%d/%m/%Y}."
            )

    for licencia in licencias:
        fin = nuevo_hasta
        if licencia.designacion.hasta and licencia.designacion.hasta < fin:
            fin = licencia.designacion.hasta
        licencia.hasta = fin
        try:
            licencia.full_clean()
        except ValidationError as exc:
            raise ValidationError(
                f"{_materia(licencia.designacion)}: {' '.join(exc.messages)}"
            ) from exc
        licencia.save()

    return licencias


@transaction.atomic
def cortar(licencias, volvio_el, usuario):
    """
    El docente volvió antes: la licencia termina el día anterior a `volvio_el`
    y los días marcados después pasan a Presente (PR) en borrador, para
    revisarlos en la diaria. Los días de un período cerrado no se tocan y se
    informan. Devuelve (días liberados, avisos).
    """
    from asistencias.models import EventoAsistencia, MarcaAsistencia, RegistroAsistencia
    from asistencias.services.reglas import _datos_registro, _validar_periodo_abierto

    nuevo_hasta = volvio_el - timedelta(days=1)

    for licencia in licencias:
        if nuevo_hasta < licencia.desde:
            raise ValidationError(
                "El docente no puede volver antes de que empiece la licencia "
                f"({licencia.desde:%d/%m/%Y})."
            )
        if licencia.hasta is not None and nuevo_hasta >= licencia.hasta:
            raise ValidationError(
                "Para cortar la licencia, el día en que volvió tiene que ser "
                f"anterior al {licencia.hasta:%d/%m/%Y} o ese mismo día."
            )

    presente = MarcaAsistencia.objects.filter(codigo="PR").first()
    if presente is None:
        raise ValidationError("No existe la marca Presente (PR).")

    liberados = []
    avisos = []

    for licencia in licencias:
        licencia.hasta = nuevo_hasta
        licencia.full_clean()
        licencia.save()

        registros = (
            RegistroAsistencia.objects.select_for_update()
            .select_related("marca")
            .filter(licencia=licencia, fecha__gt=nuevo_hasta)
        )
        for registro in registros:
            try:
                _validar_periodo_abierto(registro.fecha)
            except ValidationError:
                avisos.append(
                    f"{registro.fecha:%d/%m/%Y} ({_materia(licencia.designacion)}): "
                    "el período está cerrado, corregilo con una reapertura."
                )
                continue

            antes = _datos_registro(registro)
            registro.marca = presente
            registro.licencia = None
            registro.horas_inasistidas = Decimal("0")
            registro.estado_justificacion = RegistroAsistencia.EstadoJustificacion.NO_APLICA
            registro.nro_formulario = ""
            registro.fecha_recepcion = None
            registro.recepcionado_por = None
            registro.estado_registro = RegistroAsistencia.Estado.BORRADOR
            registro.actualizado_por = usuario
            registro.save()
            EventoAsistencia.objects.create(
                asistencia=registro,
                usuario=usuario,
                accion=EventoAsistencia.Accion.EDITAR,
                motivo=f"Licencia cortada: volvió el {volvio_el:%d/%m/%Y}",
                antes=antes,
                despues=_datos_registro(registro),
            )
            liberados.append(registro.fecha)

    return sorted(set(liberados)), avisos


def dias_del_tope(licencia):
    """(usados en el año, tope) del artículo para el docente, o None sin tope."""
    from .services import dias_usados_en_anio

    tope = licencia.articulo.tope_dias_anual
    if not tope:
        return None

    anio = licencia.desde.year
    usados = dias_usados_en_anio(
        licencia.designacion.persona.dni, licencia.articulo.articulo, anio
    )
    return {"usados": usados, "tope": tope, "quedan": max(tope - usados, 0), "anio": anio}
