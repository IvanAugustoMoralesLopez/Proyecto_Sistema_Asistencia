from django.contrib.admin.models import ADDITION, CHANGE, LogEntry
from django.db.models import Model


def registrar_cambio(usuario, objeto, *, alta=False, mensaje=""):
    """
    Deja constancia (usuario, fecha y hora, descripción) de un cambio de
    configuración en el historial del admin de Django. Se usa para los
    cambios que no generan un EventoAsistencia (usuarios y parámetros).
    Nunca incluir contraseñas en el mensaje.
    """
    modelo: type[Model] = type(objeto)
    LogEntry.objects.log_actions(
        usuario.pk,
        modelo.objects.filter(pk=objeto.pk),
        ADDITION if alta else CHANGE,
        mensaje,
        single_object=True,
    )
