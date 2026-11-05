"""
Consultas de solo lectura sobre asistencias, para otros modulos (por ejemplo,
el reporte mensual de licencias). No modifican nada.
"""

from ..models import RegistroAsistencia

# Marcas que son una inasistencia propiamente dicha. LIC y LT tambien computan
# inasistencia, pero esos dias ya se cuentan desde las licencias: incluirlos
# aca los contaria dos veces.
CODIGOS_INASISTENCIA = ("I", "PR")


def inasistencias_del_periodo(desde, hasta):
    """
    Registros de inasistencia (marcas I y PR) con fecha entre `desde` y
    `hasta`, ambas inclusive, ordenados por fecha. Trae ya cargados la marca,
    la persona, el cargo y el espacio curricular para armar el reporte sin
    consultas extra.
    """
    return (
        RegistroAsistencia.objects
        .filter(
            fecha__range=(desde, hasta),
            marca__codigo__in=CODIGOS_INASISTENCIA,
        )
        .select_related(
            "marca",
            "designacion__persona",
            "designacion__cargo",
            "designacion__espacio_curricular",
        )
        .order_by("fecha", "designacion_id")
    )