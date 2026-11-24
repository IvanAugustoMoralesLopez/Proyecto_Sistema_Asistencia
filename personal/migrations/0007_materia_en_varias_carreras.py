"""
Una materia (espacio curricular) puede estar en varias carreras.

Antes cada materia tenía una sola carrera y, si se dictaba en dos, se cargaba
dos veces. Ahora:

* `EspacioCurricular.carreras` (muchos a muchos) reemplaza a `carrera`, y el
  nombre de la materia es único.
* `Designacion.carrera` indica en cuál de esas carreras dicta el docente.

Pasos de datos:
1. Cada materia guarda su carrera actual en `carreras`, y cada designación
   toma la carrera de su materia.
2. Las materias repetidas (mismo nombre, sin distinguir mayúsculas, tildes ni
   espacios de más) se unen en una sola: se queda la de id más bajo, suma las
   carreras de las otras y les pasan sus designaciones y su historial.
"""

import unicodedata

import django.db.models.deletion
from django.db import migrations, models


def _clave(nombre):
    texto = unicodedata.normalize("NFKD", nombre or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.lower().split())


def pasar_a_varias_carreras(apps, schema_editor):
    EspacioCurricular = apps.get_model("personal", "EspacioCurricular")
    Designacion = apps.get_model("personal", "Designacion")
    HistorialDesignacion = apps.get_model("personal", "HistorialDesignacion")

    grupos = {}
    for espacio in EspacioCurricular.objects.order_by("pk"):
        espacio.carreras.add(espacio.carrera_id)
        Designacion.objects.filter(
            espacio_curricular_id=espacio.pk, carrera__isnull=True
        ).update(carrera_id=espacio.carrera_id)
        grupos.setdefault(_clave(espacio.nombre), []).append(espacio)

    for espacios in grupos.values():
        principal, repetidas = espacios[0], espacios[1:]
        for repetida in repetidas:
            principal.carreras.add(*repetida.carreras.all())
            Designacion.objects.filter(espacio_curricular_id=repetida.pk).update(
                espacio_curricular_id=principal.pk
            )
            HistorialDesignacion.objects.filter(
                espacio_curricular_id=repetida.pk
            ).update(espacio_curricular_id=principal.pk)
            if repetida.activo and not principal.activo:
                principal.activo = True
                principal.save(update_fields=["activo"])
            repetida.carreras.clear()
            repetida.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("personal", "0006_codigos_numericos_de_cargo"),
    ]

    operations = [
        migrations.AddField(
            model_name="designacion",
            name="carrera",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="designaciones",
                to="personal.carrera",
            ),
        ),
        # Nombre inverso provisorio: mientras conviven `carrera` y `carreras`
        # no pueden usar el mismo related_name.
        migrations.AddField(
            model_name="espaciocurricular",
            name="carreras",
            field=models.ManyToManyField(
                db_table="personal_espacio_curricular_carrera",
                related_name="espacios_curriculares_nuevo",
                to="personal.carrera",
            ),
        ),
        migrations.RunPython(pasar_a_varias_carreras, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="espaciocurricular",
            name="uq_espacio_carrera_mnombre",
        ),
        migrations.RemoveField(
            model_name="espaciocurricular",
            name="carrera",
        ),
        migrations.AlterField(
            model_name="espaciocurricular",
            name="carreras",
            field=models.ManyToManyField(
                db_table="personal_espacio_curricular_carrera",
                related_name="espacios_curriculares",
                to="personal.carrera",
            ),
        ),
        migrations.AlterField(
            model_name="espaciocurricular",
            name="nombre",
            field=models.CharField(max_length=120, unique=True),
        ),
        migrations.AlterModelOptions(
            name="espaciocurricular",
            options={"ordering": ["nombre"]},
        ),
    ]
