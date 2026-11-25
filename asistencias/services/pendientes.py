"""
Seguimiento de pendientes: faltas sin resolver y licencias sin completar.

Lo que se carga en la diaria y queda sin resolver no se puede olvidar:

- Falta sin resolver: inasistencia (I) injustificada, sin formulario.
- Licencia sin completar: marca LIC o LT sin licencia cargada (el docente
  avisó, pero todavía no trajo el papel con el artículo).

Plazo (en días hábiles: se saltean fines de semana y los días del
calendario escolar):

- el día de la novedad no se avisa nada;
- el día hábil siguiente aparece el aviso (naranja), que se puede posponer
  una sola vez;
- al segundo día hábil vence: el aviso es obligatorio (rojo) y no se puede
  cerrar la jornada ni el mes hasta responderlo.

La novedad es una por docente y día (RF-07): un pendiente agrupa los
registros de todas sus materias de esa fecha. Solo se siguen los registros
con seguimiento=True (los cargados desde este cambio).
"""

from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ..models import (
    DiaNoLaborable,
    EventoAsistencia,
    MarcaAsistencia,
    RegistroAsistencia,
)
from .reglas import (
    DIAS_HABILES,
    MOTIVO_MINIMO,
    _datos_registro,
    _validar_motivo_maximo,
    _validar_periodo_abierto,
)
from .sesiones import _validar_sesion_edicion

TIPO_FALTA = "falta"
TIPO_LICENCIA = "licencia"

ESTADO_EN_PLAZO = "en_plazo"   # todavía no hay que avisar
ESTADO_AVISO = "aviso"         # día hábil siguiente: aviso naranja
ESTADO_VENCIDO = "vencido"     # segundo día hábil: respuesta obligatoria

PLAZO_DIAS_HABILES = 2

CODIGO_INASISTENCIA = "I"
CODIGOS_LICENCIA = ("LIC", "LT")

# Respuestas posibles al resolver.
RESPUESTA_FORMULARIO = "formulario"       # falta: llegó el formulario
RESPUESTA_NO_LLEGO = "no_llego"           # falta: queda injustificada
RESPUESTA_NO_CORRESPONDE = "no_corresponde"  # licencia: pasa a inasistencia


def condicion_pendiente():
    """Q de los registros que hoy son un pendiente."""
    return Q(seguimiento=True, resuelto_en__isnull=True) & (
        Q(
            marca__codigo=CODIGO_INASISTENCIA,
            estado_justificacion=RegistroAsistencia.EstadoJustificacion.INJUSTIFICADA,
        )
        | Q(marca__codigo__in=CODIGOS_LICENCIA, licencia__isnull=True)
    )


def tipo_de_pendiente(registro):
    """Qué pendiente genera el registro, o None si no genera ninguno."""
    codigo = registro.marca.codigo

    if (
        codigo == CODIGO_INASISTENCIA
        and registro.estado_justificacion
        == RegistroAsistencia.EstadoJustificacion.INJUSTIFICADA
    ):
        return TIPO_FALTA

    if codigo in CODIGOS_LICENCIA and registro.licencia_id is None:
        return TIPO_LICENCIA

    return None


def iniciar_seguimiento(registro):
    """
    Marca el registro para seguimiento si quedó como pendiente. Lo llama la
    carga diaria al guardar. Un registro ya resuelto no vuelve a seguirse.
    """
    if registro.seguimiento or registro.resuelto_en is not None:
        return

    if tipo_de_pendiente(registro) is None:
        return

    registro.seguimiento = True
    registro.save(update_fields=["seguimiento"])


def _es_habil(fecha, no_laborables):
    return fecha.weekday() in DIAS_HABILES and fecha not in no_laborables


def dias_habiles_siguientes(fecha, cantidad, no_laborables=None):
    """Los `cantidad` días hábiles siguientes a `fecha`, en orden."""
    if no_laborables is None:
        no_laborables = set(
            DiaNoLaborable.objects.filter(
                fecha__gt=fecha, fecha__lte=fecha + timedelta(days=60)
            ).values_list("fecha", flat=True)
        )

    dias = []
    actual = fecha

    while len(dias) < cantidad:
        actual += timedelta(days=1)
        if _es_habil(actual, no_laborables):
            dias.append(actual)

    return dias


def plazos(fecha, no_laborables=None):
    """(día del aviso, día en que vence) para una novedad de `fecha`."""
    aviso, vence = dias_habiles_siguientes(
        fecha, PLAZO_DIAS_HABILES, no_laborables
    )
    return aviso, vence


def estado_en(aviso, vence, hoy):
    if hoy >= vence:
        return ESTADO_VENCIDO
    if hoy >= aviso:
        return ESTADO_AVISO
    return ESTADO_EN_PLAZO


def _materia(designacion):
    if designacion.espacio_curricular_id:
        return designacion.espacio_curricular.nombre
    return designacion.cargo.descripcion


def pendientes(hoy=None, *, persona_id=None, fecha=None, tipo=None):
    """
    Pendientes agrupados por docente, día y tipo, ordenados: primero los
    vencidos, después los avisos y al final los que están en plazo.

    Cada pendiente es un dict con persona, fecha, tipo, registros, materias,
    horas, aviso, vence, estado, pospuesto (bool) y clave (para los
    formularios de resolución).
    """
    hoy = hoy or timezone.localdate()

    registros = (
        RegistroAsistencia.objects.select_related(
            "marca",
            "designacion__persona",
            "designacion__cargo",
            "designacion__espacio_curricular",
            "pospuesto_por",
        )
        .filter(condicion_pendiente())
        .order_by("fecha", "designacion__persona__apellido_nombre", "designacion_id")
    )

    if persona_id is not None:
        registros = registros.filter(designacion__persona_id=persona_id)
    if fecha is not None:
        registros = registros.filter(fecha=fecha)

    grupos = {}

    for registro in registros:
        tipo_registro = tipo_de_pendiente(registro)

        if tipo_registro is None or (tipo and tipo_registro != tipo):
            continue

        clave = (registro.designacion.persona_id, registro.fecha, tipo_registro)
        grupos.setdefault(clave, []).append(registro)

    if not grupos:
        return []

    primera = min(clave[1] for clave in grupos)
    no_laborables = set(
        DiaNoLaborable.objects.filter(
            fecha__gt=primera, fecha__lte=max(hoy, primera) + timedelta(days=60)
        ).values_list("fecha", flat=True)
    )

    lista = []

    for (persona_id_grupo, fecha_grupo, tipo_grupo), del_grupo in grupos.items():
        aviso, vence = plazos(fecha_grupo, no_laborables)
        pospuesto = next(
            (r for r in del_grupo if r.pospuesto_en is not None), None
        )
        lista.append(
            {
                "persona": del_grupo[0].designacion.persona,
                "fecha": fecha_grupo,
                "tipo": tipo_grupo,
                "registros": del_grupo,
                "materias": [_materia(r.designacion) for r in del_grupo],
                "horas": sum(r.horas_inasistidas for r in del_grupo),
                "aviso": aviso,
                "vence": vence,
                "estado": estado_en(aviso, vence, hoy),
                "pospuesto": pospuesto is not None,
                "pospuesto_en": pospuesto.pospuesto_en if pospuesto else None,
                "pospuesto_por": pospuesto.pospuesto_por if pospuesto else None,
                "clave": f"{persona_id_grupo}|{fecha_grupo.isoformat()}|{tipo_grupo}",
            }
        )

    orden = {ESTADO_VENCIDO: 0, ESTADO_AVISO: 1, ESTADO_EN_PLAZO: 2}
    lista.sort(
        key=lambda p: (orden[p["estado"]], p["vence"], p["persona"].apellido_nombre)
    )
    return lista


def avisos_del_dia(hoy=None):
    """
    Lo que la carga diaria muestra arriba: los vencidos (obligatorios) y los
    avisos que todavía no se pospusieron.
    """
    return [
        p
        for p in pendientes(hoy)
        if p["estado"] == ESTADO_VENCIDO
        or (p["estado"] == ESTADO_AVISO and not p["pospuesto"])
    ]


def vencidos_al(fecha):
    """Pendientes que a esa fecha ya vencieron (bloquean los cierres)."""
    return [p for p in pendientes(fecha) if p["estado"] == ESTADO_VENCIDO]


def validar_sin_vencidos(fecha, que):
    """No deja cerrar (`que`: «la jornada», «el mes») con pendientes vencidos."""
    vencidos = vencidos_al(fecha)

    if vencidos:
        nombres = ", ".join(
            sorted({p["persona"].apellido_nombre for p in vencidos})
        )
        raise ValidationError(
            f"No se puede cerrar {que}: hay {len(vencidos)} pendiente"
            f"{'s' if len(vencidos) != 1 else ''} vencido"
            f"{'s' if len(vencidos) != 1 else ''} sin respuesta ({nombres}). "
            "Resolvelos desde la carga diaria o desde Licencias › Pendientes."
        )


def leer_clave(clave):
    """(persona_id, fecha, tipo) de la clave de un pendiente, o ValidationError."""
    from datetime import date

    try:
        persona_id, fecha_texto, tipo = clave.split("|")
        fecha = date.fromisoformat(fecha_texto)
    except (AttributeError, ValueError) as exc:
        raise ValidationError("El pendiente elegido no es válido.") from exc

    if tipo not in (TIPO_FALTA, TIPO_LICENCIA) or not persona_id.isdigit():
        raise ValidationError("El pendiente elegido no es válido.")

    return persona_id, fecha, tipo


def _el_pendiente(clave, hoy):
    persona_id, fecha, tipo = leer_clave(clave)
    encontrados = pendientes(hoy, persona_id=persona_id, fecha=fecha, tipo=tipo)

    if not encontrados:
        raise ValidationError(
            "Ese pendiente ya no existe: puede que otra persona lo haya resuelto."
        )

    return encontrados[0]


def _exigir(usuario, permiso):
    if not usuario.has_perm(permiso):
        raise PermissionDenied("No tenés permiso para resolver pendientes.")


def _registrar(registro, usuario, antes, motivo):
    EventoAsistencia.objects.create(
        asistencia=registro,
        usuario=usuario,
        accion=EventoAsistencia.Accion.EDITAR,
        motivo=motivo,
        antes=antes,
        despues=_datos_registro(registro),
    )


@transaction.atomic
def posponer(*, usuario, token, clave):
    """«Completar mañana»: solo con el aviso del día hábil siguiente y una vez."""
    _exigir(usuario, "asistencias.change_registroasistencia")
    _validar_sesion_edicion(usuario, token)
    hoy = timezone.localdate()
    pendiente = _el_pendiente(clave, hoy)

    if pendiente["estado"] == ESTADO_VENCIDO:
        raise ValidationError(
            "El plazo venció: este pendiente ya no se puede posponer."
        )
    if pendiente["pospuesto"]:
        raise ValidationError("Este pendiente ya se pospuso una vez.")

    ahora = timezone.now()

    for registro in pendiente["registros"]:
        RegistroAsistencia.objects.filter(pk=registro.pk).update(
            pospuesto_en=ahora, pospuesto_por=usuario
        )
        EventoAsistencia.objects.create(
            asistencia=registro,
            usuario=usuario,
            accion=EventoAsistencia.Accion.EDITAR,
            motivo=f"Pendiente pospuesto hasta el {pendiente['vence']:%d/%m/%Y}",
            antes=None,
            despues=None,
        )

    return pendiente


@transaction.atomic
def resolver(
    *,
    usuario,
    token,
    clave,
    respuesta,
    nro_formulario="",
    motivo="",
    nueva_marca="",
):
    """
    Responde un pendiente:

    - falta + «formulario»: queda justificada (el número es opcional). Con
      `nueva_marca` ("LIC", "LT" o "P") la I pasa a la marca del formulario
      (RF-09), igual que en Recepción de formularios. Una LIC o LT todavía
      no tiene la licencia cargada, así que sigue como «licencia sin
      completar»; un P queda resuelto.
    - falta + «no_llego»: se confirma como injustificada.
    - licencia + «no_corresponde»: pasa a inasistencia (I) con un motivo y
      sigue el circuito de faltas.

    «Era una licencia» y «Completar la licencia» no pasan por acá: abren
    Nueva licencia, que al guardar vincula los registros y los saca de la
    lista. Devuelve el pendiente, con `marca_nueva` (o None).
    """
    from .recepcion import MARCAS_AL_RECEPCIONAR

    _exigir(usuario, "asistencias.change_registroasistencia")
    _validar_sesion_edicion(usuario, token)
    _validar_motivo_maximo(motivo)
    hoy = timezone.localdate()
    pendiente = _el_pendiente(clave, hoy)
    tipo = pendiente["tipo"]
    nro_formulario = (nro_formulario or "").strip()[:30]
    ahora = timezone.now()
    Justificacion = RegistroAsistencia.EstadoJustificacion

    if tipo == TIPO_FALTA and respuesta not in (
        RESPUESTA_FORMULARIO,
        RESPUESTA_NO_LLEGO,
    ):
        raise ValidationError("Elegí si llegó o no el formulario.")
    if tipo == TIPO_LICENCIA and respuesta != RESPUESTA_NO_CORRESPONDE:
        raise ValidationError("Para completar la licencia usá «Nueva licencia».")

    if respuesta == RESPUESTA_NO_CORRESPONDE and len(motivo.strip()) < MOTIVO_MINIMO:
        raise ValidationError(
            "Indicá por qué no corresponde la licencia "
            f"(al menos {MOTIVO_MINIMO} caracteres)."
        )

    nueva_marca = (nueva_marca or "").strip().upper()
    marca_nueva = None
    if nueva_marca:
        if respuesta != RESPUESTA_FORMULARIO:
            raise ValidationError(
                "La marca del formulario solo se elige si llegó el formulario."
            )
        if nueva_marca not in MARCAS_AL_RECEPCIONAR:
            raise ValidationError(
                "Al recibir el formulario la marca solo puede pasar a "
                "Licencia (LIC), Largo tratamiento (LT) o Permiso (P)."
            )
        marca_nueva = MarcaAsistencia.objects.filter(codigo=nueva_marca).first()
        if marca_nueva is None:
            raise ValidationError(f"No existe la marca «{nueva_marca}».")

    inasistencia = None
    if respuesta == RESPUESTA_NO_CORRESPONDE:
        inasistencia = MarcaAsistencia.objects.filter(
            codigo=CODIGO_INASISTENCIA
        ).first()
        if inasistencia is None:
            raise ValidationError("No existe la marca de inasistencia (I).")

    for registro in pendiente["registros"]:
        _validar_periodo_abierto(registro.fecha)
        registro = RegistroAsistencia.objects.select_for_update().select_related(
            "marca"
        ).get(pk=registro.pk)
        antes = _datos_registro(registro)

        if respuesta == RESPUESTA_FORMULARIO:
            registro.estado_justificacion = Justificacion.JUSTIFICADA
            registro.nro_formulario = nro_formulario
            registro.fecha_recepcion = hoy
            registro.recepcionado_por = usuario
            texto = "Pendiente resuelto: llegó el formulario"

            if marca_nueva is not None:
                # RF-09: la I pasa a la marca del formulario.
                registro.marca = marca_nueva
                if marca_nueva.requiere_observacion and not registro.observaciones.strip():
                    registro.observaciones = (
                        f"{marca_nueva.descripcion} - formulario N° {nro_formulario}"
                        if nro_formulario
                        else f"{marca_nueva.descripcion} - formulario recibido"
                    )
                texto += f" ({marca_nueva.codigo})"

            if marca_nueva is not None and marca_nueva.codigo in CODIGOS_LICENCIA:
                # Falta cargar la licencia: queda como «licencia sin
                # completar», con su propia posibilidad de posponer.
                registro.pospuesto_en = None
                registro.pospuesto_por = None
            else:
                registro.resuelto_en = ahora
                registro.resuelto_por = usuario
        elif respuesta == RESPUESTA_NO_LLEGO:
            registro.resuelto_en = ahora
            registro.resuelto_por = usuario
            texto = "Pendiente resuelto: no llegó el formulario (injustificada)"
        else:
            # La licencia no corresponde: pasa a ser una falta sin resolver.
            # Su plazo se cuenta desde el día de la novedad, así que si ya
            # venció aparece enseguida como obligatoria.
            registro.marca = inasistencia
            registro.estado_justificacion = Justificacion.INJUSTIFICADA
            registro.pospuesto_en = None
            registro.pospuesto_por = None
            registro.observaciones = (
                f"{registro.observaciones} {motivo.strip()}".strip()
            )[:500]
            texto = f"Licencia que no corresponde, pasa a inasistencia: {motivo.strip()}"

        registro.estado_registro = RegistroAsistencia.Estado.BORRADOR
        registro.actualizado_por = usuario
        registro.save()
        _registrar(registro, usuario, antes, texto)

    pendiente["marca_nueva"] = marca_nueva
    return pendiente



@transaction.atomic
def confirmar_injustificadas(registros, usuario, confirmar=True):
    """
    Desde la planilla mensual (Licencias): «No corresponde (injustificada)»
    equivale a responder «No llegó» el pendiente de esas faltas. Con
    confirmar=False se deshace: la falta vuelve a esperar el papel.

    Solo toca inasistencias (I) sin justificar. Devuelve cuántas cambió.
    """
    _exigir(usuario, "asistencias.change_registroasistencia")
    Justificacion = RegistroAsistencia.EstadoJustificacion
    ahora = timezone.now()
    cambiados = 0
    for registro in registros:
        registro = RegistroAsistencia.objects.select_for_update().select_related(
            "marca"
        ).get(pk=registro.pk)
        if (
            registro.marca.codigo != CODIGO_INASISTENCIA
            or registro.estado_justificacion != Justificacion.INJUSTIFICADA
        ):
            continue
        if confirmar == (registro.resuelto_en is not None):
            continue
        _validar_periodo_abierto(registro.fecha)
        antes = _datos_registro(registro)
        if confirmar:
            registro.resuelto_en = ahora
            registro.resuelto_por = usuario
            texto = "Planilla mensual: no llegó el formulario (injustificada)"
        else:
            registro.resuelto_en = None
            registro.resuelto_por = None
            texto = "Planilla mensual: la falta vuelve a esperar el formulario"
        registro.actualizado_por = usuario
        registro.save()
        _registrar(registro, usuario, antes, texto)
        cambiados += 1
    return cambiados
