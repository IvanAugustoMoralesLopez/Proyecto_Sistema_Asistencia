"""
Vistas de asistencias.

Este paquete reemplaza al antiguo `views.py` (un solo archivo de ~910
líneas), dividido por pantalla para que sea más fácil de leer y
navegar:

- `registro`: registro diario, alta/edición individual, historial y
  validación de registros.
- `planilla`: planilla rápida (carga del día completo en una pantalla).
- `cierres`: cierre de jornada, listado de cierres y cierre/reapertura
  de períodos mensuales.
- `recepcion`: recepción del formulario en papel de las inasistencias.
- `sesion`: liberar/renovar manualmente la sesión de edición.
- `_comun`: helpers compartidos entre las vistas de arriba.

`asistencias/urls.py` sigue haciendo `from . import views` y llamando
`views.<nombre>`: este archivo reexporta exactamente la misma API
pública que tenía el `views.py` original.
"""

from .cierres import cerrar_jornada, confirmar_cierre, lista_cierres, reapertura_mensual
from .planilla import planilla_rapida
from .recepcion import recepcion_formularios, recepcionar_formulario_view
from .registro import (
    crear_asistencia,
    detalle_asistencia,
    editar_asistencia,
    historial,
    registro_diario,
    validar_registro,
)
from .sesion import liberar_edicion, renovar_edicion

__all__ = [
    "registro_diario",
    "crear_asistencia",
    "editar_asistencia",
    "historial",
    "detalle_asistencia",
    "validar_registro",
    "planilla_rapida",
    "cerrar_jornada",
    "lista_cierres",
    "confirmar_cierre",
    "reapertura_mensual",
    "recepcion_formularios",
    "recepcionar_formulario_view",
    "liberar_edicion",
    "renovar_edicion",
]
