from .selectors import texto_instrumento

ENCABEZADO_LICENCIAS = [
    "DNI", "Apellido y nombre", "Cargo", "Carrera", "Cód. licencia",
    "Artículo", "Tipo de licencia", "Sit. de revista", "Desde", "Hasta",
    "Instrumento legal", "Justifica",
]

_JUSTIFICA = {True: "Sí", False: "No", None: "Sin definir"}


def _texto_seguro(valor):
    """Evita que Excel interprete como fórmula un texto que empieza con = + - @."""
    valor = "" if valor is None else str(valor)
    return "'" + valor if valor[:1] in ("=", "+", "-", "@") else valor


def filas_licencias(licencias):
    """Genera una fila de CSV por licencia (el queryset ya viene filtrado)."""
    for lic in licencias.iterator():
        designacion = lic.designacion
        espacio = designacion.espacio_curricular
        yield [
            designacion.persona.dni,
            _texto_seguro(designacion.persona.apellido_nombre),
            _texto_seguro(designacion.cargo),
            _texto_seguro(espacio.carrera if espacio else ""),
            lic.articulo.cod_licencia,
            lic.articulo.articulo,
            _texto_seguro(lic.articulo.tipo_licencia),
            lic.sit_rev,
            lic.desde.strftime("%d/%m/%Y"),
            lic.hasta.strftime("%d/%m/%Y") if lic.hasta else "",
            _texto_seguro(texto_instrumento(lic)),
            _JUSTIFICA[lic.justifica],
        ]
