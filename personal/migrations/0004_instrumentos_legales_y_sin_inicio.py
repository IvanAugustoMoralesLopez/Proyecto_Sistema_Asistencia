"""
RF-05: catálogo de tipos de instrumento legal (con Resolución y Disposición
ya cargados) y `norma_tipo` sin lista fija.
RN-09: vigencia SIN INICIO en las designaciones.
"""

from django.db import migrations, models

INICIALES = ("Resolución", "Disposición")


def cargar_tipos(apps, schema_editor):
    TipoInstrumentoLegal = apps.get_model("personal", "TipoInstrumentoLegal")
    Designacion = apps.get_model("personal", "Designacion")

    nombres = list(INICIALES)
    # Tipos que ya estuvieran escritos en designaciones existentes.
    for nombre in (
        Designacion.objects.exclude(norma_tipo="")
        .values_list("norma_tipo", flat=True)
        .distinct()
    ):
        if nombre not in nombres:
            nombres.append(nombre)

    for nombre in nombres:
        TipoInstrumentoLegal.objects.get_or_create(nombre=nombre)


class Migration(migrations.Migration):

    dependencies = [
        ("personal", "0003_requisitos_suplencia_plan"),
    ]

    operations = [
        migrations.CreateModel(
            name="TipoInstrumentoLegal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nombre", models.CharField(max_length=30, unique=True)),
                ("activo", models.BooleanField(default=True)),
            ],
            options={
                "verbose_name": "tipo de instrumento legal",
                "verbose_name_plural": "tipos de instrumento legal",
                "db_table": "personal_tipo_instrumento_legal",
                "ordering": ["nombre"],
            },
        ),
        migrations.AlterField(
            model_name="designacion",
            name="norma_tipo",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="designacion",
            name="sin_inicio",
            field=models.BooleanField(db_default=False, default=False),
        ),
        migrations.RunPython(cargar_tipos, migrations.RunPython.noop),
    ]
