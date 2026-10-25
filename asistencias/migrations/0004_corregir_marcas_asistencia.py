from django.db import migrations

# Catálogo cerrado de marcas diarias (RF-08):
# Presente (P), Inasistencia (I), Licencia (LIC), Largo Tratamiento (LT)
# y Presente Retirado (PR). La migración 0003 había cargado P como
# "Permiso" y PR como "Presente".
MARCAS = [
    dict(
        codigo="P",
        descripcion="Presente",
        computa_inasistencia=False,
        requiere_observacion=False,
        requiere_horas=False,
        requiere_licencia=False,
    ),
    dict(
        codigo="I",
        descripcion="Inasistencia",
        computa_inasistencia=True,
        requiere_observacion=False,
        requiere_horas=True,
        requiere_licencia=False,
    ),
    dict(
        codigo="LIC",
        descripcion="Licencia",
        computa_inasistencia=True,
        requiere_observacion=False,
        requiere_horas=True,
        requiere_licencia=True,
    ),
    dict(
        codigo="LT",
        descripcion="Largo tratamiento",
        computa_inasistencia=True,
        requiere_observacion=False,
        requiere_horas=True,
        requiere_licencia=True,
    ),
    dict(
        codigo="PR",
        descripcion="Presente retirado",
        computa_inasistencia=True,
        requiere_observacion=True,
        requiere_horas=True,
        requiere_licencia=False,
    ),
]


def corregir_marcas(apps, schema_editor):
    MarcaAsistencia = apps.get_model("asistencias", "MarcaAsistencia")

    for datos in MARCAS:
        MarcaAsistencia.objects.update_or_create(
            codigo=datos["codigo"],
            defaults={**datos, "activa": True},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('asistencias', '0003_seed_marcas_asistencia'),
    ]

    operations = [
        migrations.RunPython(corregir_marcas, migrations.RunPython.noop),
    ]
