"""
Nomenclador oficial de licencias (catálogo de artículos).

- `leer_nomenclador`: lee y valida el CSV de licencias/data/nomenclador.csv.
- `cargar_nomenclador`: crea o actualiza los artículos por código.
- `motivo_de` / `articulo_para`: un mismo motivo (1-1, enfermedad común) tiene
  un artículo distinto según la situación de revista (309 B 1 para titular,
  331-A para interino, 340-A para suplente). Lo que los une son los dos
  primeros números del código.
- `reemplazar_inventados`: pasa las licencias y los renglones que usan los
  artículos de prueba (T-14, T-15...) a los del nomenclador y los borra.
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import transaction

from .clasificacion import PLANILLA_POR_CATEGORIA
from .models import LicenciaArticulo, LicenciaOtorgada, RenglonMensual

RUTA_CSV = Path(__file__).resolve().parent / "data" / "nomenclador.csv"

AGRUPACIONES = {
    "1": "Salud",
    "2": "Otras licencias",
    "3": "Permisos",
}

COLUMNAS = (
    "codigo", "agrupacion", "motivo", "articulo", "sit_rev", "goce_haberes",
    "autoridad", "plazo", "tope_dias_anual", "clase", "categoria",
)

# Artículos de prueba de la semilla → códigos del nomenclador, en orden de
# preferencia. Un motivo (dos números) toma el artículo de la situación de
# revista de cada licencia; un código completo vale solo si es de esa
# situación. Si ninguno existe para ella, se usa Inasistencias (2-13), que
# está para titulares, interinos y suplentes.
REEMPLAZOS_INVENTADOS = {
    "T-14": ("1-1",),           # Enfermedad común
    "T-15": ("1-2",),           # Largo tratamiento
    "T-22": ("2-9", "2-13"),    # Examen (no hay de suplentes → inasistencia)
    "T-20": ("2-4-1", "2-13"),  # Razones particulares → fuerza mayor (solo titulares)
    "T-25": ("3-4",),           # Duelo → familiar de 1er grado
}


def motivo_de(codigo):
    """'1-1-3' → '1-1'. Los códigos que no son del nomenclador devuelven ''."""
    partes = (codigo or "").split("-")
    if len(partes) != 3 or not all(p.isdigit() for p in partes):
        return ""
    return f"{partes[0]}-{partes[1]}"


def agrupacion_de(codigo):
    motivo = motivo_de(codigo)
    return motivo.split("-")[0] if motivo else ""


def es_del_nomenclador(articulo):
    return bool(motivo_de(articulo.cod_licencia))


def _orden_codigo(codigo):
    return tuple(int(p) if p.isdigit() else 0 for p in codigo.split("-"))


# ───────────── Lectura y carga ─────────────

def leer_nomenclador(ruta=RUTA_CSV):
    """
    Lee el CSV y devuelve una lista de dicts listos para el modelo.
    Si alguna fila es inválida, lanza ValidationError con todas las filas
    con problemas (no se carga nada a medias).
    """
    situaciones = {valor for valor, _ in LicenciaArticulo.SIT_REV_CHOICES}
    clases = {valor for valor, _ in LicenciaArticulo.CLASE_CHOICES}
    largo = {
        campo: LicenciaArticulo._meta.get_field(campo).max_length
        for campo in ("cod_licencia", "articulo", "tipo_licencia", "goce_haberes", "autoridad", "plazo")
    }

    filas, errores, vistos = [], [], set()
    with open(ruta, encoding="utf-8-sig", newline="") as archivo:
        lector = csv.DictReader(archivo)
        faltan = [c for c in COLUMNAS if c not in (lector.fieldnames or [])]
        if faltan:
            raise ValidationError(f"Al archivo le faltan columnas: {', '.join(faltan)}.")

        for numero, fila in enumerate(lector, start=2):
            fila = {clave: (valor or "").strip() for clave, valor in fila.items()}
            codigo = fila["codigo"]
            problemas = []
            if not motivo_de(codigo):
                problemas.append(f"código «{codigo}» inválido")
            if codigo in vistos:
                problemas.append(f"código «{codigo}» repetido")
            if fila["sit_rev"] not in situaciones:
                problemas.append(f"situación de revista «{fila['sit_rev']}»")
            if fila["clase"] not in clases:
                problemas.append(f"clase «{fila['clase']}»")
            if fila["categoria"] not in PLANILLA_POR_CATEGORIA:
                problemas.append(f"categoría «{fila['categoria']}» sin planilla (RN-04/RN-05)")
            tope = fila["tope_dias_anual"]
            if tope and not tope.isdigit():
                problemas.append(f"tope «{tope}» no es un número")
            valores = {
                "cod_licencia": codigo,
                "articulo": fila["articulo"],
                "tipo_licencia": fila["motivo"],
                "goce_haberes": fila["goce_haberes"],
                "autoridad": fila["autoridad"],
                "plazo": fila["plazo"],
            }
            for campo, valor in valores.items():
                if len(valor) > largo[campo]:
                    problemas.append(f"{campo} pasa de {largo[campo]} caracteres")

            if problemas:
                errores.append(f"Fila {numero} ({codigo}): " + "; ".join(problemas))
                continue
            vistos.add(codigo)
            filas.append({
                **valores,
                "sit_rev": fila["sit_rev"],
                "clase": fila["clase"],
                "categoria_informe": fila["categoria"],
                "tope_dias_anual": int(tope) if tope else None,
            })

    if errores:
        raise ValidationError(errores)
    return filas


@dataclass
class ResultadoCarga:
    creados: list = field(default_factory=list)
    actualizados: list = field(default_factory=list)
    sin_cambios: list = field(default_factory=list)


@transaction.atomic
def cargar_nomenclador(filas, guardar=True):
    """
    Crea o actualiza un artículo por código (`cod_licencia`). Se puede correr
    las veces que haga falta. Con guardar=False solo informa qué haría.
    """
    resultado = ResultadoCarga()
    existentes = {a.cod_licencia: a for a in LicenciaArticulo.objects.all()}

    for fila in filas:
        articulo = existentes.get(fila["cod_licencia"])
        if articulo is None:
            resultado.creados.append(fila["cod_licencia"])
            if guardar:
                LicenciaArticulo.objects.create(**fila)
            continue

        cambios = {k: v for k, v in fila.items() if getattr(articulo, k) != v}
        if not cambios:
            resultado.sin_cambios.append(fila["cod_licencia"])
            continue
        resultado.actualizados.append(fila["cod_licencia"])
        if guardar:
            for campo, valor in cambios.items():
                setattr(articulo, campo, valor)
            articulo.save(update_fields=list(cambios))

    if not guardar:
        transaction.set_rollback(True)
    return resultado


# ───────────── Equivalencia por situación de revista ─────────────

def articulo_para(articulo, situacion):
    """
    El artículo del mismo motivo que corresponde a `situacion` ('Titular',
    'Interino', 'Suplente'). Prefiere la misma forma de pago. Devuelve None
    si el nomenclador no tiene ese motivo para esa situación de revista.

    Para un artículo que no es del nomenclador (los de prueba), busca el mismo
    número de artículo, como hacía el sistema antes.
    """
    if articulo is None:
        return None
    situacion = (situacion or "").strip()
    if not situacion or (articulo.sit_rev or "").strip().lower() == situacion.lower():
        return articulo

    motivo = motivo_de(articulo.cod_licencia)
    if not motivo:
        return LicenciaArticulo.objects.filter(
            articulo=articulo.articulo, sit_rev__iexact=situacion,
        ).first()

    candidatos = sorted(
        (
            a for a in LicenciaArticulo.objects.filter(
                cod_licencia__startswith=f"{motivo}-", sit_rev__iexact=situacion,
            )
            if motivo_de(a.cod_licencia) == motivo
        ),
        key=lambda a: _orden_codigo(a.cod_licencia),
    )
    for candidato in candidatos:
        if candidato.goce_haberes == articulo.goce_haberes:
            return candidato
    return candidatos[0] if candidatos else None


def motivos_para(situaciones=()):
    """
    Motivos para elegir en Nueva licencia, agrupados:
    [(agrupación, [ {motivo, nombre, representante, situaciones} ])].

    Con `situaciones` (las del docente) se muestran los motivos que existen
    para al menos una de ellas. `representante` es el artículo que se envía
    al elegir el motivo: el de la primera situación del docente, con goce si
    lo hay; el sistema después pone el de cada materia.
    Los artículos que no son del nomenclador van al final, en «Otros».
    """
    orden = [s.lower() for s in situaciones if s]
    por_motivo, otros = {}, []
    for articulo in LicenciaArticulo.objects.all():
        motivo = motivo_de(articulo.cod_licencia)
        if motivo:
            por_motivo.setdefault(motivo, []).append(articulo)
        elif not orden or (articulo.sit_rev or "").lower() in orden:
            otros.append(articulo)

    grupos = {}
    for motivo, articulos in sorted(por_motivo.items(), key=lambda par: _orden_codigo(par[0])):
        articulos.sort(key=lambda a: _orden_codigo(a.cod_licencia))
        tiene = [(a.sit_rev or "").lower() for a in articulos]
        if orden and not set(orden) & set(tiene):
            continue

        def prioridad(a):
            situacion = (a.sit_rev or "").lower()
            puesto = orden.index(situacion) if situacion in orden else len(orden)
            return (puesto, a.goce_haberes != "Con goce de haberes", _orden_codigo(a.cod_licencia))

        grupos.setdefault(motivo.split("-")[0], []).append({
            "motivo": motivo,
            "nombre": articulos[0].tipo_licencia,
            "representante": min(articulos, key=prioridad),
            "situaciones": sorted({a.sit_rev for a in articulos}),
        })

    resultado = [(AGRUPACIONES.get(clave, clave), grupos[clave]) for clave in sorted(grupos)]
    if otros:
        resultado.append(("Otros (sin código del nomenclador)", [
            {"motivo": a.cod_licencia, "nombre": f"{a.articulo} - {a.tipo_licencia}",
             "representante": a, "situaciones": [a.sit_rev]}
            for a in sorted(otros, key=lambda a: a.cod_licencia)
        ]))
    return resultado


# ───────────── Reemplazo de los artículos de prueba ─────────────

@dataclass
class ResultadoReemplazo:
    cambios: list = field(default_factory=list)       # (tipo, id, de, a, docente)
    sin_equivalente: list = field(default_factory=list)  # (tipo, id, de, situacion, docente)
    borrados: list = field(default_factory=list)


def _destino(origen, situacion, articulos):
    situacion = (situacion or origen.sit_rev or "").lower()
    for destino in REEMPLAZOS_INVENTADOS.get(origen.cod_licencia, ()):
        if motivo_de(destino):  # código completo: vale si es de esa situación
            elegido = articulos.get(destino)
            if elegido is not None and (elegido.sit_rev or "").lower() == situacion:
                return elegido
            continue
        candidatos = sorted(
            (a for a in articulos.values()
             if motivo_de(a.cod_licencia) == destino
             and (a.sit_rev or "").lower() == situacion),
            key=lambda a: _orden_codigo(a.cod_licencia),
        )
        for candidato in candidatos:
            if candidato.goce_haberes == origen.goce_haberes:
                return candidato
        if candidatos:
            return candidatos[0]
    return None


@transaction.atomic
def reemplazar_inventados(guardar=True):
    """
    Pasa las licencias otorgadas y los renglones de la planilla que usan un
    artículo de prueba al artículo del nomenclador que le corresponde, y
    borra los de prueba que quedan sin uso. Con guardar=False solo informa.
    """
    resultado = ResultadoReemplazo()
    articulos = {a.cod_licencia: a for a in LicenciaArticulo.objects.all()}
    inventados = [articulos[c] for c in REEMPLAZOS_INVENTADOS if c in articulos]
    quedan_en_uso = set()

    for licencia in LicenciaOtorgada.objects.filter(articulo__in=inventados).select_related(
        "articulo", "designacion__persona"
    ):
        situacion = licencia.sit_rev or (
            licencia.designacion.get_situacion_revista_display()
            if licencia.designacion.situacion_revista else ""
        )
        destino = _destino(licencia.articulo, situacion, articulos)
        docente = licencia.designacion.persona.apellido_nombre
        if destino is None:
            resultado.sin_equivalente.append(
                ("licencia", licencia.pk, licencia.articulo.cod_licencia, situacion, docente)
            )
            quedan_en_uso.add(licencia.articulo.cod_licencia)
            continue
        resultado.cambios.append(
            ("licencia", licencia.pk, licencia.articulo.cod_licencia, destino.cod_licencia, docente)
        )
        if guardar:
            # update() y no save(): solo cambia el encuadre, no se vuelven a
            # validar fechas ni topes de licencias que ya estaban otorgadas.
            LicenciaOtorgada.objects.filter(pk=licencia.pk).update(articulo=destino)

    for renglon in RenglonMensual.objects.filter(articulo__in=inventados).select_related(
        "articulo", "designacion__persona"
    ):
        situacion = (
            renglon.designacion.get_situacion_revista_display()
            if renglon.designacion.situacion_revista else ""
        )
        destino = _destino(renglon.articulo, situacion, articulos)
        docente = renglon.designacion.persona.apellido_nombre
        if destino is None:
            resultado.sin_equivalente.append(
                ("renglón", renglon.pk, renglon.articulo.cod_licencia, situacion, docente)
            )
            quedan_en_uso.add(renglon.articulo.cod_licencia)
            continue
        resultado.cambios.append(
            ("renglón", renglon.pk, renglon.articulo.cod_licencia, destino.cod_licencia, docente)
        )
        if guardar:
            renglon.imputar(destino)
            renglon.save(update_fields=["articulo", "cod_licencia", "planilla"])

    for articulo in inventados:
        if articulo.cod_licencia in quedan_en_uso:
            continue
        resultado.borrados.append(articulo.cod_licencia)
        if guardar:
            articulo.delete()

    if not guardar:
        transaction.set_rollback(True)
    return resultado
