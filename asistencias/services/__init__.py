"""
Reglas de negocio de asistencias.

Las reglas de negocio se agregan acá, no en los archivos HTML ni en las
vistas. Cada operación que modifica datos debe estar dentro de una
transacción. Si una regla cambia —por ejemplo, permitir cerrar un mes
con borradores— se modifica el servicio correspondiente y se agrega una
prueba. Los errores esperados deben lanzarse como ValidationError o
PermissionDenied; las excepciones inesperadas deben registrarse y
corregirse, no ocultarse con un except Exception genérico.

Este paquete reemplaza al antiguo `services.py` (un solo archivo de
~840 líneas), dividido por responsabilidad para que sea más fácil de
leer y navegar:

- `sesiones`: concurrencia y sesión de edición.
- `reglas`: validaciones compartidas (período, jornada, designación,
  marca, licencia) usadas por los comandos de abajo.
- `registro`: alta y modificación de asistencias, individual o por
  planilla (RF-07).
- `recepcion`: recepción del formulario en papel (RF-09) y validación
  de registros.
- `cierres`: cierre y reapertura de jornadas (RN-06) y períodos
  mensuales.

Todo lo que antes se importaba con `from asistencias.services import X`
se sigue importando igual: este archivo reexporta la misma API pública.
"""

from .cierres import cerrar_dia, cerrar_mes, reabrir_mes
from .recepcion import (
    TRANSICIONES_JUSTIFICACION,
    recepcionar_formulario,
    validar_asistencia,
)
from .registro import PlanillaConErrores, guardar_asistencia, guardar_planilla
from .reglas import (
    DIAS_HABILES,
    MOTIVO_MINIMO,
    motivo_dia_no_laborable,
    validar_dia_laborable,
)
from .sesiones import (
    MAX_OPERADORES,
    MINUTOS_EXPIRACION_SESION,
    adquirir_sesion_edicion,
    liberar_sesion_edicion,
    renovar_sesion_edicion,
)

__all__ = [
    "MAX_OPERADORES",
    "MINUTOS_EXPIRACION_SESION",
    "MOTIVO_MINIMO",
    "DIAS_HABILES",
    "TRANSICIONES_JUSTIFICACION",
    "PlanillaConErrores",
    "adquirir_sesion_edicion",
    "renovar_sesion_edicion",
    "liberar_sesion_edicion",
    "motivo_dia_no_laborable",
    "validar_dia_laborable",
    "guardar_asistencia",
    "guardar_planilla",
    "recepcionar_formulario",
    "validar_asistencia",
    "cerrar_dia",
    "cerrar_mes",
    "reabrir_mes",
]
