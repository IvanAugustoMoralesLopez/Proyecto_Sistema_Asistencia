from django.db import migrations


def marcar_inasistencias_injustificadas(apps, schema_editor):
    """
    Los registros anteriores a RF-09 que computan inasistencia quedan
    como injustificadas hasta que se recepcione el formulario en papel.
    """
    RegistroAsistencia = apps.get_model("asistencias", "RegistroAsistencia")

    RegistroAsistencia.objects.filter(
        marca__computa_inasistencia=True,
        estado_justificacion="NO_APLICA",
    ).update(estado_justificacion="INJUSTIFICADA")


class Migration(migrations.Migration):

    dependencies = [
        ('asistencias', '0005_rf09_recepcion_formularios'),
    ]

    operations = [
        migrations.RunPython(
            marcar_inasistencias_injustificadas,
            migrations.RunPython.noop,
        ),
    ]
