from asistencias.models import EventoAsistencia


def registrar_evento(usuario, accion, *, motivo="", antes=None, despues=None):
    """
    Deja un evento en la bitácora (RF-20) para cambios de configuración que
    no están ligados a un registro de asistencia: usuarios y parámetros.
    Nunca incluir contraseñas en antes/despues.
    """
    return EventoAsistencia.objects.create(
        usuario=usuario,
        accion=accion,
        motivo=motivo,
        antes=antes,
        despues=despues,
    )


def datos_usuario(usuario, rol):
    """Foto de los datos de un usuario que interesan para auditar."""
    return {
        "usuario": usuario.username,
        "nombre": usuario.first_name,
        "apellido": usuario.last_name,
        "email": usuario.email,
        "activo": usuario.is_active,
        "rol": rol,
    }
