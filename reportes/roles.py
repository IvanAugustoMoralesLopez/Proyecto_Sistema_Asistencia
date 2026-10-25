"""
Roles del sistema (RF-19): Bedelía, Secretaría y Subsecretaría.

Cada rol es un grupo de Django con un conjunto de permisos. Los permisos
de Secretaría incluyen los de Bedelía, y los de Subsecretaría los de
Secretaría (RN-06: reabrir o modificar lo cerrado requiere nivel Secretaría
o superior).
"""

from django.contrib.auth.models import Group, Permission

BEDELIA = "Bedelía"
SECRETARIA = "Secretaría"
SUBSECRETARIA = "Subsecretaría"
ROLES = (BEDELIA, SECRETARIA, SUBSECRETARIA)

_BEDELIA = [
    ("asistencias", "add_registroasistencia"),
    ("asistencias", "change_registroasistencia"),
    ("asistencias", "recepcionar_formulario"),
    ("asistencias", "cerrar_jornada"),
    ("reportes", "consultar_licencias"),
]
_SECRETARIA = _BEDELIA + [
    ("asistencias", "validar_registro"),
    ("asistencias", "modificar_jornada_cerrada"),
    ("asistencias", "cerrar_periodo"),
    ("asistencias", "change_cierremensual"),
    ("reportes", "ver_bitacora"),
]
_SUBSECRETARIA = _SECRETARIA + [
    ("reportes", "gestionar_parametros"),
    ("reportes", "gestionar_usuarios"),
]

PERMISOS_POR_ROL = {
    BEDELIA: _BEDELIA,
    SECRETARIA: _SECRETARIA,
    SUBSECRETARIA: _SUBSECRETARIA,
}


def _permisos_de(nombre, using):
    return [
        Permission.objects.using(using).get(
            content_type__app_label=app,
            codename=codename,
        )
        for app, codename in PERMISOS_POR_ROL[nombre]
    ]


def crear_grupos(using="default"):
    """
    Crea los grupos que todavía no existen y les asigna sus permisos.
    Un grupo que ya existe no se toca, así los ajustes hechos a mano
    desde el admin no se pisan en cada migrate.
    """
    for nombre in PERMISOS_POR_ROL:
        grupo, creado = Group.objects.using(using).get_or_create(name=nombre)
        if creado:
            grupo.permissions.add(*_permisos_de(nombre, using))


def restablecer_grupos(using="default"):
    """Deja los tres grupos exactamente con los permisos por defecto."""
    for nombre in PERMISOS_POR_ROL:
        grupo, _ = Group.objects.using(using).get_or_create(name=nombre)
        grupo.permissions.set(_permisos_de(nombre, using))
