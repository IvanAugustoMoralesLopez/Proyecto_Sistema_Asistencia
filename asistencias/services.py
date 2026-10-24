#Las reglas de negocio se agregan aca, no en los archivos HTML.
#Cada operación que modifica datos debe estar dentro de una transacción.
#Si una regla cambia —por ejemplo, permitir cerrar un mes con borradores— se modifica el servicio y se agrega una prueba.
#Los errores esperados deben lanzarse como ValidationError o PermissionDenied; 
#las excepciones inesperadas deben registrarse y corregirse, no ocultarse con un except Exception genérico.


from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (
    RegistroAsistencia,
    MarcaAsistencia,
    CierreDiario,
    CierreMensual,
    EventoAsistencia,
    ControlConcurrencia,
    DiaNoLaborable,
    SesionEdicion,
    licencia_cubre_fecha,
)


MAX_OPERADORES = 2
MINUTOS_EXPIRACION_SESION = 15
MOTIVO_MINIMO = 10

# Días en los que existe obligación de marcado (lunes a viernes).
DIAS_HABILES = (0, 1, 2, 3, 4)


def _exigir_permiso(usuario, permiso, mensaje):
    if not usuario.has_perm(permiso):
        raise PermissionDenied(mensaje)


def _obtener_control_bloqueado():
    """
    Obtiene el registro coordinador dentro de una transacción.
    Todas las operaciones que cambien las sesiones activas deben
    bloquear esta misma fila antes de contar o insertar sesiones.
    """
    try:
        return ControlConcurrencia.objects.select_for_update().get(pk=1)
    except ControlConcurrencia.DoesNotExist as exc:
        raise RuntimeError(
            "No existe el control de concurrencia. "
            "Ejecutá las migraciones y verificá las señales."
        ) from exc


@transaction.atomic
def adquirir_sesion_edicion(usuario, token):
    """
    Registra una sesión de trabajo para un usuario autenticado.
    El token debe conservarse en la sesión de Django.
    """
    if not usuario.is_authenticated:
        raise PermissionDenied("Debés iniciar sesión.")

    _obtener_control_bloqueado()
    ahora = timezone.now()

    SesionEdicion.objects.filter(
        activa=True,
        expira_en__lte=ahora,
    ).update(activa=False)

    sesion_existente = SesionEdicion.objects.filter(
        token=token,
        activa=True,
    ).first()

    if sesion_existente:
        if sesion_existente.usuario_id != usuario.pk:
            raise PermissionDenied(
                "El token de edición pertenece a otro usuario."
            )

        sesion_existente.heartbeat_en = ahora
        sesion_existente.expira_en = (
            ahora + timedelta(minutes=MINUTOS_EXPIRACION_SESION)
        )
        sesion_existente.save(
            update_fields=["heartbeat_en", "expira_en"]
        )
        return sesion_existente

    cantidad = SesionEdicion.objects.filter(
        activa=True,
        expira_en__gt=ahora,
    ).count()

    if cantidad >= MAX_OPERADORES:
        raise ValidationError(
            "Ya hay dos operadores activos en asistencia. "
            "Intentá nuevamente más tarde."
        )

    return SesionEdicion.objects.create(
        usuario=usuario,
        token=token,
        heartbeat_en=ahora,
        expira_en=ahora + timedelta(
            minutes=MINUTOS_EXPIRACION_SESION
        ),
        activa=True,
    )


@transaction.atomic
def renovar_sesion_edicion(usuario, token):
    """
    Renueva la sesión activa de un operador.
    Se llama desde una petición autenticada, no desde un temporizador
    sin autenticación.
    """
    _obtener_control_bloqueado()

    ahora = timezone.now()

    try:
        sesion = SesionEdicion.objects.select_for_update().get(
            token=token,
            usuario=usuario,
            activa=True,
            expira_en__gt=ahora,
        )
    except SesionEdicion.DoesNotExist as exc:
        raise ValidationError(
            "La sesión de edición expiró. Volvé a ingresar."
        ) from exc

    sesion.heartbeat_en = ahora
    sesion.expira_en = ahora + timedelta(
        minutes=MINUTOS_EXPIRACION_SESION
    )
    sesion.save(update_fields=["heartbeat_en", "expira_en"])

    return sesion


@transaction.atomic
def liberar_sesion_edicion(usuario, token):
    _obtener_control_bloqueado()

    SesionEdicion.objects.filter(
        usuario=usuario,
        token=token,
        activa=True,
    ).update(activa=False)


def _validar_sesion_edicion(usuario, token):
    if not token:
        raise PermissionDenied(
            "No existe una sesión de edición activa."
        )

    ahora = timezone.now()

    try:
        return SesionEdicion.objects.get(
            usuario=usuario,
            token=token,
            activa=True,
            expira_en__gt=ahora,
        )
    except SesionEdicion.DoesNotExist as exc:
        raise PermissionDenied(
            "La sesión de edición expiró. Volvé a ingresar."
        ) from exc


def _periodo_de_fecha(fecha):
    return CierreMensual.objects.filter(
        anio=fecha.year,
        mes=fecha.month,
    ).first()


def _validar_periodo_abierto(fecha):
    cierre = _periodo_de_fecha(fecha)

    if cierre and cierre.estado == CierreMensual.Estado.CERRADO:
        raise ValidationError(
            "El período está cerrado. Solicitá una reapertura autorizada."
        )

    return cierre


def _validar_jornada_abierta(usuario, fecha, motivo):
    """
    RN-06: modificar una jornada cerrada requiere autorización de
    Secretaría o Subsecretaría y queda justificado con un motivo.
    """
    if not CierreDiario.objects.filter(fecha=fecha).exists():
        return

    _exigir_permiso(
        usuario,
        "asistencias.modificar_jornada_cerrada",
        f"La jornada del {fecha:%d/%m/%Y} está cerrada: modificarla "
        "requiere autorización de Secretaría o Subsecretaría.",
    )

    if len(motivo.strip()) < MOTIVO_MINIMO:
        raise ValidationError(
            f"La jornada del {fecha:%d/%m/%Y} está cerrada: indicá el "
            f"motivo de la modificación (al menos {MOTIVO_MINIMO} "
            "caracteres)."
        )


def motivo_dia_no_laborable(fecha):
    """
    Devuelve el motivo por el que la fecha no tiene obligación de marcado
    (feriado, asueto, día inhábil o fin de semana), o None si es hábil.
    """
    dia = DiaNoLaborable.objects.filter(fecha=fecha).first()

    if dia:
        texto = f"{fecha:%d/%m/%Y} es {dia.get_tipo_display().lower()}"

        if dia.descripcion:
            texto += f" ({dia.descripcion})"

        return texto

    if fecha.weekday() not in DIAS_HABILES:
        return f"{fecha:%d/%m/%Y} es fin de semana"

    return None


def validar_dia_laborable(fecha):
    motivo = motivo_dia_no_laborable(fecha)

    if motivo:
        raise ValidationError(
            f"{motivo}: no corresponde registrar asistencia."
        )


def _validar_designacion_vigente(designacion, fecha):
    if not designacion.activo:
        raise ValidationError("La designación está inactiva.")

    if not designacion.persona.activa:
        raise ValidationError("La persona está inactiva.")

    if fecha < designacion.desde:
        raise ValidationError(
            "La fecha es anterior al inicio de la designación."
        )

    if designacion.hasta and fecha > designacion.hasta:
        raise ValidationError(
            "La fecha es posterior al fin de la designación."
        )


def _validar_marca_requisitos(marca, horas_inasistidas, licencia):
    """
    Aplica las reglas de la marca sobre horas y licencia (equivalentes al
    CHECK de la tabla `asistencia` del diseño de base de datos: Presente
    sin horas ni licencia, Ausente con horas, Licencia con horas y una
    licencia vinculada).
    """
    horas_inasistidas = horas_inasistidas or Decimal("0")

    if marca.requiere_horas and horas_inasistidas <= Decimal("0"):
        raise ValidationError(
            "La marca seleccionada requiere indicar horas "
            "inasistidas mayores a cero."
        )

    if not marca.requiere_horas:
        horas_inasistidas = Decimal("0")

    if marca.requiere_licencia and licencia is None:
        raise ValidationError(
            "La marca seleccionada requiere una licencia vinculada."
        )

    return horas_inasistidas


def _validar_licencia(registro):
    if not registro.licencia_id:
        return

    licencia = registro.licencia

    if licencia.designacion_id != registro.designacion_id:
        raise ValidationError(
            "La licencia no pertenece a esta designación."
        )

    if not licencia_cubre_fecha(licencia, registro.fecha):
        raise ValidationError(
            "La fecha de asistencia está fuera del período de licencia."
        )


def _datos_registro(registro):
    return {
        "designacion_id": registro.designacion_id,
        "fecha": registro.fecha.isoformat(),
        "marca": registro.marca.codigo,
        "estado_registro": registro.estado_registro,
        "horas_inasistidas": str(registro.horas_inasistidas),
        "licencia_id": registro.licencia_id,
        "observaciones": registro.observaciones,
        "estado_justificacion": registro.estado_justificacion,
        "nro_formulario": registro.nro_formulario,
        "fecha_recepcion": (
            registro.fecha_recepcion.isoformat()
            if registro.fecha_recepcion
            else None
        ),
    }


def _ajustar_justificacion(registro):
    """
    Toda inasistencia nace injustificada hasta recibir el formulario en
    papel. Si la marca deja de computar inasistencia, el registro vuelve
    a "no aplica" y se descartan los datos del formulario.
    """
    Justificacion = RegistroAsistencia.EstadoJustificacion

    if not registro.marca.computa_inasistencia:
        registro.estado_justificacion = Justificacion.NO_APLICA
        registro.nro_formulario = ""
        registro.fecha_recepcion = None
        registro.recepcionado_por = None
    elif registro.estado_justificacion == Justificacion.NO_APLICA:
        registro.estado_justificacion = Justificacion.INJUSTIFICADA


@transaction.atomic
def guardar_asistencia(
    *,
    usuario,
    token,
    datos,
    registro_id=None,
    motivo="",
):
    """
    Crea o modifica una asistencia.
    Todas las modificaciones relevantes quedan registradas en eventos.
    """
    if registro_id is None:
        _exigir_permiso(
            usuario,
            "asistencias.add_registroasistencia",
            "No tenés permiso para registrar asistencia.",
        )
    else:
        _exigir_permiso(
            usuario,
            "asistencias.change_registroasistencia",
            "No tenés permiso para modificar asistencia.",
        )

    _validar_sesion_edicion(usuario, token)

    designacion = datos["designacion"]
    fecha = datos["fecha"]

    _validar_periodo_abierto(fecha)
    _validar_jornada_abierta(usuario, fecha, motivo)
    validar_dia_laborable(fecha)
    _validar_designacion_vigente(designacion, fecha)

    marca = datos["marca"]
    observaciones = datos.get("observaciones", "")

    if marca.requiere_observacion and not observaciones.strip():
        raise ValidationError(
            "La marca seleccionada requiere observaciones."
        )

    licencia = datos.get("licencia")
    horas_inasistidas = _validar_marca_requisitos(
        marca, datos.get("horas_inasistidas"), licencia
    )

    if registro_id is None:
        registro = RegistroAsistencia(
            designacion=designacion,
            fecha=fecha,
            marca=marca,
            horas_inasistidas=horas_inasistidas,
            licencia=licencia,
            observaciones=observaciones,
            creado_por=usuario,
            actualizado_por=usuario,
        )
        _ajustar_justificacion(registro)
        registro.full_clean()
        _validar_licencia(registro)

        try:
            registro.save()
        except IntegrityError as exc:
            raise ValidationError(
                "Ya existe un registro para esa designación y fecha."
            ) from exc

        accion = EventoAsistencia.Accion.CREAR
        antes = None

    else:
        try:
            registro = (
                RegistroAsistencia.objects.select_for_update()
                .select_related("marca", "licencia")
                .get(pk=registro_id)
            )
        except RegistroAsistencia.DoesNotExist as exc:
            raise ValidationError(
                "El registro que intentás modificar no existe."
            ) from exc

        _validar_periodo_abierto(registro.fecha)

        if registro.fecha != fecha:
            _validar_jornada_abierta(usuario, registro.fecha, motivo)

        antes = _datos_registro(registro)

        # Un registro validado solo se corrige con motivo y vuelve a
        # borrador para que se valide nuevamente.
        if registro.estado_registro == RegistroAsistencia.Estado.VALIDADO:
            if len(motivo.strip()) < MOTIVO_MINIMO:
                raise ValidationError(
                    "Para modificar un registro validado indicá el motivo "
                    f"del cambio (al menos {MOTIVO_MINIMO} caracteres)."
                )

            registro.estado_registro = RegistroAsistencia.Estado.BORRADOR

        registro.designacion = designacion
        registro.fecha = fecha
        registro.marca = marca
        registro.horas_inasistidas = horas_inasistidas
        registro.licencia = licencia
        registro.observaciones = observaciones
        registro.actualizado_por = usuario
        _ajustar_justificacion(registro)

        registro.full_clean()
        _validar_licencia(registro)
        registro.save()

        accion = EventoAsistencia.Accion.EDITAR

    EventoAsistencia.objects.create(
        asistencia=registro,
        usuario=usuario,
        accion=accion,
        motivo=motivo,
        antes=antes,
        despues=_datos_registro(registro),
    )

    return registro


class PlanillaConErrores(Exception):
    """Filas de la planilla rápida con errores: {designacion_id: mensaje}."""

    def __init__(self, errores):
        super().__init__("La planilla tiene filas con errores.")
        self.errores = errores


@transaction.atomic
def guardar_planilla(*, usuario, token, fecha, filas, motivo=""):
    """
    Registra de una vez las marcas de un día (RF-07). Cada fila es un dict
    con designacion, marca, horas_inasistidas, licencia y observaciones.
    Es todo o nada: si alguna fila falla no se guarda ninguna.
    """
    _exigir_permiso(
        usuario,
        "asistencias.add_registroasistencia",
        "No tenés permiso para registrar asistencia.",
    )
    _validar_sesion_edicion(usuario, token)

    if not filas:
        raise ValidationError("No marcaste ninguna asistencia.")

    # Errores que alcanzan a toda la planilla: se informan una sola vez.
    _validar_periodo_abierto(fecha)
    _validar_jornada_abierta(usuario, fecha, motivo)
    validar_dia_laborable(fecha)

    errores = {}
    registros = []

    for fila in filas:
        try:
            registros.append(
                guardar_asistencia(
                    usuario=usuario,
                    token=token,
                    datos={**fila, "fecha": fecha},
                    motivo=motivo,
                )
            )
        except ValidationError as exc:
            errores[fila["designacion"].pk] = " ".join(exc.messages)

    if errores:
        raise PlanillaConErrores(errores)

    return registros


TRANSICIONES_JUSTIFICACION = {
    RegistroAsistencia.EstadoJustificacion.INJUSTIFICADA: {
        RegistroAsistencia.EstadoJustificacion.EN_TRAMITE,
        RegistroAsistencia.EstadoJustificacion.JUSTIFICADA,
    },
    RegistroAsistencia.EstadoJustificacion.EN_TRAMITE: {
        RegistroAsistencia.EstadoJustificacion.JUSTIFICADA,
        RegistroAsistencia.EstadoJustificacion.INJUSTIFICADA,
    },
}


@transaction.atomic
def recepcionar_formulario(
    *,
    usuario,
    token,
    registro_id,
    nuevo_estado,
    nro_formulario="",
    fecha_recepcion=None,
    motivo="",
):
    """
    Cambia el estado de justificación de una inasistencia al recibir (o
    rechazar) el formulario en papel. Injustificada pasa a en trámite o
    justificada; en trámite pasa a justificada o vuelve a injustificada.
    """
    _exigir_permiso(
        usuario,
        "asistencias.recepcionar_formulario",
        "No tenés permiso para recepcionar formularios.",
    )
    _validar_sesion_edicion(usuario, token)

    Justificacion = RegistroAsistencia.EstadoJustificacion

    try:
        registro = (
            RegistroAsistencia.objects.select_for_update()
            .select_related("marca")
            .get(pk=registro_id)
        )
    except RegistroAsistencia.DoesNotExist as exc:
        raise ValidationError(
            "El registro que intentás modificar no existe."
        ) from exc

    _validar_periodo_abierto(registro.fecha)

    if not registro.marca.computa_inasistencia:
        raise ValidationError(
            "El registro no es una inasistencia: no admite formulario."
        )

    if nuevo_estado not in Justificacion.values:
        raise ValidationError("El estado de justificación no es válido.")

    if nuevo_estado not in TRANSICIONES_JUSTIFICACION.get(
        registro.estado_justificacion, set()
    ):
        raise ValidationError(
            "No se puede pasar de "
            f"{registro.get_estado_justificacion_display().lower()} a "
            f"{Justificacion(nuevo_estado).label.lower()}."
        )

    nro_formulario = nro_formulario.strip()
    motivo = motivo.strip()

    if nuevo_estado == Justificacion.INJUSTIFICADA:
        if len(motivo) < MOTIVO_MINIMO:
            raise ValidationError(
                "Para rechazar el formulario indicá el motivo "
                f"(al menos {MOTIVO_MINIMO} caracteres)."
            )

        nro_formulario = ""
        fecha_recepcion = None
    else:
        if not nro_formulario:
            raise ValidationError(
                "Indicá el número del formulario recepcionado."
            )

        fecha_recepcion = fecha_recepcion or timezone.localdate()

        if fecha_recepcion > timezone.localdate():
            raise ValidationError(
                "La fecha de recepción no puede ser futura."
            )

    antes = _datos_registro(registro)

    registro.estado_justificacion = nuevo_estado
    registro.nro_formulario = nro_formulario
    registro.fecha_recepcion = fecha_recepcion
    registro.recepcionado_por = (
        usuario if nuevo_estado != Justificacion.INJUSTIFICADA else None
    )
    registro.actualizado_por = usuario
    registro.save()

    EventoAsistencia.objects.create(
        asistencia=registro,
        usuario=usuario,
        accion=EventoAsistencia.Accion.RECEPCIONAR,
        motivo=motivo,
        antes=antes,
        despues=_datos_registro(registro),
    )

    return registro


@transaction.atomic
def validar_asistencia(*, usuario, token, registro_id):
    _exigir_permiso(
        usuario,
        "asistencias.validar_registro",
        "No tenés permiso para validar registros.",
    )
    _validar_sesion_edicion(usuario, token)

    registro = (
        RegistroAsistencia.objects.select_for_update()
        .select_related("designacion", "marca")
        .get(pk=registro_id)
    )

    _validar_periodo_abierto(registro.fecha)

    registro.full_clean()
    _validar_licencia(registro)

    antes = _datos_registro(registro)
    registro.estado_registro = RegistroAsistencia.Estado.VALIDADO
    registro.actualizado_por = usuario
    registro.save()

    EventoAsistencia.objects.create(
        asistencia=registro,
        usuario=usuario,
        accion=EventoAsistencia.Accion.VALIDAR,
        antes=antes,
        despues=_datos_registro(registro),
    )

    return registro


@transaction.atomic
def cerrar_dia(*, usuario, token, fecha):
    """
    Cierra la jornada (RN-06). Desde ese momento modificar sus registros
    requiere el permiso `modificar_jornada_cerrada` y un motivo.
    """
    _exigir_permiso(
        usuario,
        "asistencias.cerrar_jornada",
        "No tenés permiso para cerrar la jornada.",
    )
    _validar_sesion_edicion(usuario, token)

    if fecha > timezone.localdate():
        raise ValidationError("No se puede cerrar una jornada futura.")

    motivo = motivo_dia_no_laborable(fecha)

    if motivo:
        raise ValidationError(f"{motivo}: no hay jornada para cerrar.")

    _validar_periodo_abierto(fecha)

    cierre, creado = CierreDiario.objects.get_or_create(
        fecha=fecha,
        defaults={"cerrado_por": usuario},
    )

    if not creado:
        raise ValidationError("La jornada ya está cerrada.")

    EventoAsistencia.objects.create(
        cierre_diario=cierre,
        usuario=usuario,
        accion=EventoAsistencia.Accion.CERRAR_DIA,
        despues={
            "fecha": fecha.isoformat(),
            "registros": RegistroAsistencia.objects.filter(
                fecha=fecha
            ).count(),
        },
    )

    return cierre


@transaction.atomic
def cerrar_mes(*, usuario, anio, mes, token):
    _exigir_permiso(
        usuario,
        "asistencias.cerrar_periodo",
        "No tenés permiso para cerrar períodos.",
    )
    _validar_sesion_edicion(usuario, token)
    _obtener_control_bloqueado()

    if not 1 <= mes <= 12:
        raise ValidationError("El mes debe estar entre 1 y 12.")

    cierre, _ = CierreMensual.objects.select_for_update().get_or_create(
        anio=anio,
        mes=mes,
    )

    if cierre.estado == CierreMensual.Estado.CERRADO:
        raise ValidationError("El período ya está cerrado.")

    pendientes = RegistroAsistencia.objects.filter(
        fecha__year=anio,
        fecha__month=mes,
        estado_registro=RegistroAsistencia.Estado.BORRADOR,
    ).exists()

    if pendientes:
        raise ValidationError(
            "No se puede cerrar: hay registros sin validar."
        )

    cierre.estado = CierreMensual.Estado.CERRADO
    cierre.cerrado_por = usuario
    cierre.cerrado_en = timezone.now()
    cierre.reabierto_por = None
    cierre.reabierto_en = None
    cierre.motivo_reapertura = ""
    cierre.version += 1
    cierre.save()

    EventoAsistencia.objects.create(
        cierre=cierre,
        usuario=usuario,
        accion=EventoAsistencia.Accion.CERRAR,
        despues={
            "anio": anio,
            "mes": mes,
            "estado": cierre.estado,
            "version": cierre.version,
        },
    )

    return cierre


@transaction.atomic
def reabrir_mes(*, usuario, anio, mes, motivo, token):
    if not usuario.has_perm("asistencias.change_cierremensual"):
        raise PermissionDenied(
            "No tenés permiso para reabrir períodos."
        )

    _validar_sesion_edicion(usuario, token)
    _obtener_control_bloqueado()

    motivo = motivo.strip()

    if len(motivo) < MOTIVO_MINIMO:
        raise ValidationError(
            "El motivo de reapertura debe tener al menos "
            f"{MOTIVO_MINIMO} caracteres."
        )

    cierre = CierreMensual.objects.select_for_update().get(
        anio=anio,
        mes=mes,
    )

    if cierre.estado != CierreMensual.Estado.CERRADO:
        raise ValidationError("El período no está cerrado.")

    antes = {
        "anio": cierre.anio,
        "mes": cierre.mes,
        "estado": cierre.estado,
        "version": cierre.version,
    }

    cierre.estado = CierreMensual.Estado.ABIERTO
    cierre.reabierto_por = usuario
    cierre.reabierto_en = timezone.now()
    cierre.motivo_reapertura = motivo
    cierre.version += 1
    cierre.save()

    EventoAsistencia.objects.create(
        cierre=cierre,
        usuario=usuario,
        accion=EventoAsistencia.Accion.REABRIR,
        motivo=motivo,
        antes=antes,
        despues={
            "anio": cierre.anio,
            "mes": cierre.mes,
            "estado": cierre.estado,
            "version": cierre.version,
        },
    )

    return cierre


