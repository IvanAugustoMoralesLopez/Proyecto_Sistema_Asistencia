ENCABEZADO_CONSULTA = [
    "Origen", "DNI", "Apellido y nombre", "Cargo", "Carrera", "Materia",
    "Cód. licencia", "Artículo", "Tipo / marca", "Sit. de revista",
    "Desde", "Hasta", "Instrumento legal / formulario", "Justifica",
]


def _texto_seguro(valor):
    """Evita que Excel interprete como fórmula un texto que empieza con = + - @."""
    valor = "" if valor is None else str(valor)
    return "'" + valor if valor[:1] in ("=", "+", "-", "@") else valor


def filas_consulta(filas):
    """Genera una fila de CSV por cada FilaConsulta (ya filtrada y ordenada)."""
    for fila in filas:
        yield [
            fila.origen,
            fila.dni,
            _texto_seguro(fila.docente),
            _texto_seguro(fila.cargo),
            _texto_seguro(fila.carrera),
            _texto_seguro(fila.materia),
            fila.codigo,
            fila.articulo,
            _texto_seguro(fila.tipo),
            fila.sit_rev,
            fila.desde.strftime("%d/%m/%Y"),
            fila.hasta.strftime("%d/%m/%Y") if fila.hasta else "",
            _texto_seguro(fila.instrumento),
            fila.justifica,
        ]
