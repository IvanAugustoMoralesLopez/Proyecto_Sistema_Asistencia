from datetime import date

from django.db import DatabaseError, connection
from django.db.models import Q

from .clasificacion import planilla_para_categoria
from .db_errores import traducir_error_bd
from .dias import contar_dias_habiles, obtener_feriados, rango_en_anio
from .models import LicenciaOtorgada


def dias_usados_en_anio(dni: str, articulo: str, anio: int) -> int:
    """Días hábiles consumidos por el docente en `anio` para el artículo dado."""
    licencias = LicenciaOtorgada.objects.filter(
        designacion__persona__dni=dni,
        articulo__articulo=articulo,
        anulada=False,
        desde__year__lte=anio,
    ).filter(
        Q(hasta__isnull=True) | Q(hasta__year__gte=anio)
    )

    # Una sola consulta de feriados para todo el año (antes era una por licencia).
    feriados = obtener_feriados(date(anio, 1, 1), date(anio, 12, 31))
    hoy = date.today()

    total_dias = 0
    for lic in licencias:
        rango = rango_en_anio(lic.desde, lic.hasta, anio, hoy)
        if rango is None:
            continue
        inicio, fin = rango
        total_dias += contar_dias_habiles(inicio, fin, feriados)

    return total_dias


def clasificar_planilla_licencia(licencia: LicenciaOtorgada) -> str:
    """
    Planilla de la licencia: IL-01 (salud, RN-04) o IL-02 (administrativas, RN-05),
    según `categoria_informe` del artículo. Lanza CategoriaSinPlanillaError si el
    dato del catálogo no es válido.
    """
    return planilla_para_categoria(licencia.articulo.categoria_informe)


# ---------------------------------------------------------------------------
# Procedimientos almacenados de la base (RN-07 / RF-14 y RF-16 / RN-11)
# ---------------------------------------------------------------------------
def _llamar_procedimiento(nombre: str, args: list):
    """
    Ejecuta un procedimiento y devuelve el primer valor de su resultado.

    Los procedimientos hacen START TRANSACTION / COMMIT por su cuenta, así que
    confirman cualquier transacción abierta. Por eso se niega a correr dentro de
    transaction.atomic() o ATOMIC_REQUESTS: llamalo con transaction.on_commit()
    o fuera del bloque atómico.
    """
    if connection.in_atomic_block:
        raise RuntimeError(
            f"{nombre} confirma la transacción abierta: llamalo fuera de "
            f"transaction.atomic() (por ejemplo con transaction.on_commit)."
        )
    try:
        with connection.cursor() as cursor:
            cursor.callproc(nombre, args)
            fila = cursor.fetchone()
    except DatabaseError as exc:
        error = traducir_error_bd(exc)
        if error is not None:
            raise error from exc
        raise
    return fila[0] if fila else 0


def propagar_licencia(licencia_id: int) -> int:
    """
    RN-07 / RF-14 / RF-13: marca LIC o LT en `asistencia` para cada día con clase
    de la licencia y calcula las horas afectadas. Devuelve las filas afectadas.
    Requiere que la licencia tenga fecha `hasta`.
    """
    return _llamar_procedimiento('sp_propagar_licencia', [licencia_id])


def asignar_disposiciones(anio: int, mes: int, oficina: str = '1452') -> int:
    """
    RF-16 / RN-11 / RN-10: emite las disposiciones internas del mes, una por
    agente, ordenadas por apellido y nombre, con numeración correlativa del año
    y la oficina. Devuelve la cantidad de disposiciones emitidas en ese mes.
    """
    return _llamar_procedimiento('sp_asignar_disposiciones', [anio, mes, oficina])
