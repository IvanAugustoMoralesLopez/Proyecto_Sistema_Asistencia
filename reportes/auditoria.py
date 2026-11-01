import json

from django.core.serializers.json import DjangoJSONEncoder

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


def a_json(valores):
    """Pasa fechas, decimales, etc. a tipos que acepta un JSONField."""
    return json.loads(json.dumps(valores, cls=DjangoJSONEncoder))


def foto_en_base(modelo, pk):
    """Valores actuales de un registro tal como están en la base (o None)."""
    fila = modelo.objects.filter(pk=pk).values().first()
    return a_json(fila) if fila else None
