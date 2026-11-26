"""
RF-20: las altas, modificaciones y bajas del calendario escolar (RF-10)
quedan en la bitácora. Solo agrega opciones al campo `accion`; no cambia
datos ni columnas.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('asistencias', '0012_seguimiento_pendientes'),
    ]

    operations = [
        migrations.AlterField(
            model_name='eventoasistencia',
            name='accion',
            field=models.CharField(choices=[('CREAR', 'Crear'), ('EDITAR', 'Editar'), ('VALIDAR', 'Validar'), ('RECEPCIONAR', 'Recepcionar formulario'), ('CERRAR_DIA', 'Cerrar jornada'), ('CERRAR', 'Cerrar período'), ('REABRIR', 'Reabrir período'), ('PARAMETROS', 'Modificar parámetros'), ('USUARIO_ALTA', 'Alta de usuario'), ('USUARIO_EDITAR', 'Modificar usuario'), ('CALENDARIO_ALTA', 'Alta en el calendario'), ('CALENDARIO_EDITAR', 'Modificar el calendario'), ('CALENDARIO_BAJA', 'Baja del calendario')], max_length=20),
        ),
    ]
