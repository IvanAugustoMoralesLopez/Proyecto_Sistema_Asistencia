"""
Vocabulario más formal en el catálogo de marcas: «Vino» pasa a «Asistió».

La migración 0009 no se toca porque ya está aplicada: el cambio de redacción
va en una migración nueva, con su función inversa.
"""

from django.db import migrations


# codigo: (descripcion_simple, ayuda)
NUEVOS = {
    "P": (
        "Asistió",
        "El docente cumplió su jornada completa.",
    ),
    "I": (
        "Faltó",
        "No asistió. Pedí las horas que no cubrió. Nace como injustificada "
        "hasta que traiga el certificado.",
    ),
    "PR": (
        "Asistió y se retiró",
        "Asistió pero no cumplió toda la jornada. CUENTA COMO INASISTENCIA: "
        "pedí las horas que no cubrió y escribí el motivo.",
    ),
}

ANTERIORES = {
    "P": (
        "Vino",
        "El docente cumplió su jornada completa.",
    ),
    "I": (
        "Faltó",
        "No vino. Pedí las horas que no cubrió. Nace como injustificada "
        "hasta que traiga el certificado.",
    ),
    "PR": (
        "Vino y se retiró",
        "Vino pero no cumplió toda la jornada. CUENTA COMO INASISTENCIA: "
        "pedí las horas que no cubrió y escribí el motivo.",
    ),
}


def _aplicar(apps, textos):
    MarcaAsistencia = apps.get_model("asistencias", "MarcaAsistencia")

    for codigo, (simple, ayuda) in textos.items():
        MarcaAsistencia.objects.filter(codigo=codigo).update(
            descripcion_simple=simple,
            ayuda=ayuda,
        )


def poner_formal(apps, schema_editor):
    _aplicar(apps, NUEVOS)


def volver_atras(apps, schema_editor):
    _aplicar(apps, ANTERIORES)


class Migration(migrations.Migration):

    dependencies = [
        ("asistencias", "0009_marcas_lenguaje_llano"),
    ]

    operations = [
        migrations.RunPython(poner_formal, volver_atras),
    ]
