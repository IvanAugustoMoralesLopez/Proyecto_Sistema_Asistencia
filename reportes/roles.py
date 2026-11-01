"""
Roles del sistema (RF-19): Bedelía, Secretaría y Subsecretaría.

Cada rol es un grupo de Django con un conjunto de permisos. Los permisos
de Secretaría incluyen los de Bedelía, y los de Subsecretaría los de
Secretaría (RN-06: reabrir o modificar lo cerrado requiere nivel Secretaría
o superior).

Matriz propuesta para Personal y Licencias (ajustarla con el equipo):
Bedelía carga y corrige licencias; Secretaría suma legajos y designaciones;
Subsecretaría suma los catálogos. Después de cambiar esta matriz hay que
ejecutar `python manage.py sincronizar_roles`: los grupos que ya existen en
la base no se modifican solos.
"""

from django.contrib.auth.models import Group, Permission

BEDELIA = "Bedelía"
SECRETARIA = "Secretaría"
SUBSECRETARIA = "Subsecretaría"
ROLES = (BEDELIA, SECRETARIA, SUBSECRETARIA)

_BEDELIA = [
    # Lectura de asistencias (registro diario, historial, detalle, cierres y
    # recepción de formularios): solo para usuarios con algún rol (M5).
    ("asistencias", "view_registroasistencia"),
    ("asistencias", "add_registroasistencia"),
    ("asistencias", "change_registroasistencia"),
    ("asistencias", "recepcionar_formulario"),
    ("asistencias", "cerrar_jornada"),
    ("reportes", "consultar_licencias"),
    # Licencias otorgadas: cargar, consultar y corregir (pantallas de licencias).
    ("licencias", "add_licenciaotorgada"),
    ("licencias", "view_licenciaotorgada"),
    ("licencias", "change_licenciaotorgada"),
]
_SECRETARIA = _BEDELIA + [
    ("asistencias", "validar_registro"),
    ("asistencias", "modificar_jornada_cerrada"),
    ("asistencias", "cerrar_periodo"),
    ("asistencias", "change_cierremensual"),
    ("reportes", "ver_bitacora"),
    # Legajos y designaciones (pantalla de legajos, alta de designaciones y
    # planilla de designaciones de la página de inicio).
    ("personal", "add_persona"),
    ("personal", "change_persona"),
    ("personal", "add_designacion"),
    ("personal", "change_designacion"),
]
_SUBSECRETARIA = _SECRETARIA + [
    ("reportes", "gestionar_parametros"),
    ("reportes", "gestionar_usuarios"),
    # Catálogos: cargos, carreras, espacios curriculares y tipos de licencia.
    ("personal", "add_cargo"),
    ("personal", "change_cargo"),
    ("personal", "add_carrera"),
    ("personal", "change_carrera"),
    ("personal", "add_espaciocurricular"),
    ("personal", "change_espaciocurricular"),
    ("licencias", "add_licenciaarticulo"),
    ("licencias", "change_licenciaarticulo"),
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
