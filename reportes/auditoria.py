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


class AccionesReportes:
    """
    Acciones de auditoría que registra reportes (RF-20) además de las de
    `EventoAsistencia.Accion`. Son códigos de texto: el campo `accion` es un
    CharField, así que no hace falta tocar el modelo de asistencias.
    """

    LICENCIA_ALTA = "LICENCIA_ALTA"
    LICENCIA_EDITAR = "LICENCIA_EDITAR"
    LICENCIA_BAJA = "LICENCIA_BAJA"
    CATALOGO_ALTA = "CATALOGO_ALTA"
    CATALOGO_EDITAR = "CATALOGO_EDITAR"
    CATALOGO_BAJA = "CATALOGO_BAJA"
    IMPORTACION = "IMPORTACION"

    CHOICES = [
        (LICENCIA_ALTA, "Alta de licencia"),
        (LICENCIA_EDITAR, "Modificar licencia"),
        (LICENCIA_BAJA, "Baja de licencia"),
        (CATALOGO_ALTA, "Alta en catálogo"),
        (CATALOGO_EDITAR, "Modificar catálogo"),
        (CATALOGO_BAJA, "Baja en catálogo"),
        (IMPORTACION, "Importación CSV"),
    ]


def opciones_de_accion():
    """Todas las acciones de la bitácora (sin repetir si el modelo ya las tiene)."""
    base = list(EventoAsistencia.Accion.choices)
    existentes = {codigo for codigo, _ in base}
    return base + [c for c in AccionesReportes.CHOICES if c[0] not in existentes]


def etiqueta_de_accion(codigo):
    return dict(opciones_de_accion()).get(codigo, codigo)
