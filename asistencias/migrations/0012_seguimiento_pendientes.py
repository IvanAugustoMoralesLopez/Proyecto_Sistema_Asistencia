"""
Seguimiento de pendientes (faltas sin resolver y licencias sin completar)
y número de formulario opcional.

- Agrega a RegistroAsistencia los campos del seguimiento: si el registro se
  sigue, quién lo pospuso y cuándo, quién lo resolvió y cuándo. Los
  registros que ya existen quedan sin seguimiento (seguimiento=False), así
  lo cargado antes de este cambio no aparece como vencido.
- Quita ck_asist_formulario_requerido: el documento pide recibir el
  formulario en papel (RF-09), no registrar su número.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("asistencias", "0011_marcas_v2_permiso_presente"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="registroasistencia",
            name="ck_asist_formulario_requerido",
        ),
        migrations.AddField(
            model_name="registroasistencia",
            name="seguimiento",
            field=models.BooleanField(db_default=False, default=False),
        ),
        migrations.AddField(
            model_name="registroasistencia",
            name="pospuesto_en",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="registroasistencia",
            name="pospuesto_por",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="pendientes_pospuestos",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="registroasistencia",
            name="resuelto_en",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="registroasistencia",
            name="resuelto_por",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="pendientes_resueltos",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
