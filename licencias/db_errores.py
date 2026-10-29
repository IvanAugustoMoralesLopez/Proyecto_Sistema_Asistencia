"""
Traducción de errores de reglas que lanza la base de datos.

Los triggers y procedimientos de planilla_personal.sql hacen
SIGNAL SQLSTATE '45000' (RN-06, RN-09, superposición de licencias, tipo de
disposición...). MySQL/MariaDB los devuelve con el código 1644; sin traducir,
el usuario ve un error 500 en vez del mensaje de la regla.
"""
from contextlib import contextmanager

from django.core.exceptions import ValidationError
from django.db import DatabaseError

CODIGO_SIGNAL = 1644  # ER_SIGNAL_EXCEPTION


def traducir_error_bd(exc):
    """
    ValidationError con el mensaje de la regla si `exc` viene de un
    SIGNAL SQLSTATE '45000'; None si es cualquier otro error de base de datos.
    """
    args = getattr(exc, 'args', ())
    if len(args) >= 2 and args[0] == CODIGO_SIGNAL:
        return ValidationError(str(args[1]))
    return None


@contextmanager
def errores_de_regla():
    """
    Convierte los errores de reglas de la BD en ValidationError.

        try:
            with errores_de_regla():
                with transaction.atomic():
                    licencia.save()
        except ValidationError as e:
            form.add_error(None, e)

    Va AFUERA de transaction.atomic: dentro de un atomic una transacción con
    error ya no se puede seguir usando.
    """
    try:
        yield
    except DatabaseError as exc:
        error = traducir_error_bd(exc)
        if error is None:
            raise
        raise error from exc
