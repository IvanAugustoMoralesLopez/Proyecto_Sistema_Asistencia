"""
Modelos de asistencias.

Igual que `services/` y `views/`, el paquete está dividido por
responsabilidad:

- `marcas`: catálogo cerrado de marcas diarias (RF-08).
- `registro`: el registro de asistencia (RF-07) y la regla de
  cobertura de una licencia.
- `cierres`: cierre de la jornada diaria y del período mensual (RN-06).
- `eventos`: auditoría de cada alta o cambio.
- `sesiones`: concurrencia y sesión de edición.
- `calendario`: feriados, asuetos y días inhábiles (RF-10).

Todo lo que antes se importaba con `from asistencias.models import X`
se sigue importando igual: este paquete reexporta la misma API
pública que tenía el `models.py` original.
"""

from .marcas import CODIGOS_MARCA, MarcaAsistencia
from .registro import RegistroAsistencia, licencia_cubre_fecha
from .cierres import CierreDiario, CierreMensual
from .eventos import EventoAsistencia
from .sesiones import ControlConcurrencia, SesionEdicion
from .calendario import DiaNoLaborable

__all__ = [
    "CODIGOS_MARCA",
    "MarcaAsistencia",
    "RegistroAsistencia",
    "licencia_cubre_fecha",
    "CierreDiario",
    "CierreMensual",
    "EventoAsistencia",
    "ControlConcurrencia",
    "SesionEdicion",
    "DiaNoLaborable",
]
