ENCABEZADO_CONSULTA = [
    "Origen", "DNI", "Apellido y nombre", "Cargo", "Carrera", "Materia",
    "Cód. licencia", "Artículo", "Tipo / marca", "Sit. de revista",
    "Desde", "Hasta", "Instrumento legal / formulario", "Justifica",
]


# Caracteres con los que Excel/LibreOffice interpretan una celda como fórmula
# (incluye TAB y CR, que algunas versiones ignoran antes del signo).
_PREFIJOS_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _texto_seguro(valor):
    """Evita que una planilla interprete como fórmula un texto que empieza con = + - @ TAB o CR."""
    valor = "" if valor is None else str(valor)
    return "'" + valor if valor.startswith(_PREFIJOS_FORMULA) else valor


def filas_consulta(filas):
    """
    Genera una fila de CSV por cada FilaConsulta (ya filtrada y ordenada).
    Todas las columnas de texto pasan por _texto_seguro; las fechas se
    formatean aparte.
    """
    for fila in filas:
        yield [
            _texto_seguro(fila.origen),
            _texto_seguro(fila.dni),
            _texto_seguro(fila.docente),
            _texto_seguro(fila.cargo),
            _texto_seguro(fila.carrera),
            _texto_seguro(fila.materia),
            _texto_seguro(fila.codigo),
            _texto_seguro(fila.articulo),
            _texto_seguro(fila.tipo),
            _texto_seguro(fila.sit_rev),
            fila.desde.strftime("%d/%m/%Y"),
            fila.hasta.strftime("%d/%m/%Y") if fila.hasta else "",
            _texto_seguro(fila.instrumento),
            _texto_seguro(fila.justifica),
        ]
