from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("personal", "0002_especialidad_importacionpersonalerror_motivo_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="carrera",
            name="plan_vigente",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="carrera",
            name="plan_vigente_desde",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="carrera",
            name="plan_vigente_hasta",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="designacion",
            name="es_suplencia",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="designacion",
            name="plazo_indeterminado",
            field=models.BooleanField(default=False),
        ),
    ]
