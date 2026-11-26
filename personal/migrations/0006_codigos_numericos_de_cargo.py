"""
Los códigos de cargo pasan a ser los numéricos oficiales:

    150  Secretaría
    155  Director de Estudio
    165  Bedel
    166  Horas cátedra

Crea los cuatro cargos (si no existen) y reasigna a ellos las designaciones y
el historial que usaban un código con letras (por ejemplo «HC»). El cargo viejo
se elige por su descripción. Los códigos con letras que quedan sin uso se
borran; uno que no se pueda identificar y siga en uso se deja como está para
corregirlo a mano desde Personal → Catálogos → Cargos.

La columna sigue siendo texto: solo se agrega la validación de «solo números»,
así no hay que cambiar el tipo de la clave primaria ni de las claves foráneas.
"""

import unicodedata

import django.core.validators
from django.db import migrations, models


CARGOS_OFICIALES = (
    # (código, descripción, es_docente, palabras para reconocer el cargo viejo)
    ("150", "Secretaría", False, ("SECRETARI",)),
    ("155", "Director de Estudio", False, ("DIRECTOR",)),
    ("165", "Bedel", False, ("BEDEL",)),
    ("166", "Horas cátedra", True, ("HORA", "CATEDRA")),
)

# Códigos con letras conocidos que equivalen a uno oficial.
EQUIVALENCIAS = {"HC": "166"}


def _normalizar(texto):
    sin_tildes = unicodedata.normalize("NFKD", texto or "")
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return sin_tildes.upper()


def _codigo_oficial(cargo):
    if cargo.codigo.upper() in EQUIVALENCIAS:
        return EQUIVALENCIAS[cargo.codigo.upper()]
    descripcion = _normalizar(cargo.descripcion)
    for codigo, _descripcion, _docente, palabras in CARGOS_OFICIALES:
        if all(palabra in descripcion for palabra in palabras):
            return codigo
    return None


def pasar_a_codigos_numericos(apps, schema_editor):
    Cargo = apps.get_model("personal", "Cargo")
    Designacion = apps.get_model("personal", "Designacion")
    HistorialDesignacion = apps.get_model("personal", "HistorialDesignacion")

    for codigo, descripcion, es_docente, _palabras in CARGOS_OFICIALES:
        Cargo.objects.get_or_create(
            codigo=codigo,
            defaults={
                "descripcion": descripcion,
                "es_docente": es_docente,
                "activo": True,
            },
        )

    for cargo in list(Cargo.objects.all()):
        if cargo.codigo.isdigit():
            continue

        nuevo = _codigo_oficial(cargo)
        if nuevo:
            # update() no pasa por Designacion.save(): es una corrección de
            # datos, no un cambio de la designación, y no deja historial.
            Designacion.objects.filter(cargo_id=cargo.codigo).update(cargo_id=nuevo)
            HistorialDesignacion.objects.filter(cargo_id=cargo.codigo).update(
                cargo_id=nuevo
            )

        if not Designacion.objects.filter(cargo_id=cargo.codigo).exists():
            cargo.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("personal", "0005_historial_usuario"),
    ]

    operations = [
        migrations.AlterField(
            model_name="cargo",
            name="codigo",
            field=models.CharField(
                max_length=10,
                primary_key=True,
                serialize=False,
                validators=[
                    django.core.validators.RegexValidator(
                        "^\\d+$",
                        "El código del cargo debe ser numérico (por ejemplo 166).",
                    )
                ],
            ),
        ),
        migrations.RunPython(pasar_a_codigos_numericos, migrations.RunPython.noop),
    ]
