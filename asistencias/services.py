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
    CierreMensual,
    EventoAsistencia,
    ControlConcurrencia,
    SesionEdicion,
)


MAX_OPERADORES = 2
MINUTOS_EXPIRACION_SESION = 15


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


def _validar_licencia(registro):
    if not registro.licencia_id:
        return

    licencia = registro.licencia

    if licencia.designacion_id != registro.designacion_id:
        raise ValidationError(
            "La licencia no pertenece a esta designación."
        )

    if licencia.estado != licencia.Estado.APROBADA:
        raise ValidationError("La licencia no está aprobada.")

    if not licencia.desde <= registro.fecha <= licencia.hasta:
        raise ValidationError(
            "La fecha de asistencia está fuera del período de licencia."
        )


def _datos_registro(registro):
    return {
        "designacion_id": registro.designacion_id,
        "fecha": registro.fecha.isoformat(),
        "marca": registro.marca.codigo,
        "estado_registro": registro.estado_registro,
        "horas_inasistidas": (
            str(registro.horas_inasistidas)
            if registro.horas_inasistidas is not None
            else None
        ),
        "licencia_id": registro.licencia_id,
        "observaciones": registro.observaciones,
    }


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
    _validar_sesion_edicion(usuario, token)

    designacion = datos["designacion"]
    fecha = datos["fecha"]

    _validar_periodo_abierto(fecha)
    _validar_designacion_vigente(designacion, fecha)

    marca = datos["marca"]
    observaciones = datos.get("observaciones", "")

    if marca.requiere_observacion and not observaciones.strip():
        raise ValidationError(
            "La marca seleccionada requiere observaciones."
        )

    if (
        datos.get("horas_inasistidas") is not None
        and datos["horas_inasistidas"] < Decimal("0")
    ):
        raise ValidationError(
            "Las horas inasistidas no pueden ser negativas."
        )

    if registro_id is None:
        registro = RegistroAsistencia(
            designacion=designacion,
            fecha=fecha,
            marca=marca,
            horas_inasistidas=datos.get("horas_inasistidas"),
            licencia=datos.get("licencia"),
            observaciones=observaciones,
            creado_por=usuario,
            actualizado_por=usuario,
        )
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

        antes = _datos_registro(registro)

        registro.designacion = designacion
        registro.fecha = fecha
        registro.marca = marca
        registro.horas_inasistidas = datos.get("horas_inasistidas")
        registro.licencia = datos.get("licencia")
        registro.observaciones = observaciones
        registro.actualizado_por = usuario

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


@transaction.atomic
def validar_asistencia(*, usuario, token, registro_id):
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
def cerrar_mes(*, usuario, anio, mes, token):
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

    if len(motivo) < 10:
        raise ValidationError(
            "El motivo de reapertura debe tener al menos 10 caracteres."
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


