"""
Licencia por docente: las LicenciaOtorgada de un mismo pedido (una por
materia o cargo) comparten un grupo.

Las licencias que ya existen se agrupan por docente, artículo y período: las
que coinciden en los tres pasan a ser un mismo pedido. La vuelta atrás borra
el campo.
"""

import uuid

from django.db import migrations, models


def agrupar(apps, schema_editor):
    LicenciaOtorgada = apps.get_model("licencias", "LicenciaOtorgada")
    grupos = {}

    for licencia in LicenciaOtorgada.objects.select_related("designacion").order_by("pk"):
        clave = (
            licencia.designacion.persona_id,
            licencia.articulo_id,
            licencia.desde,
            licencia.hasta,
        )
        grupo = grupos.setdefault(clave, uuid.uuid4())
        LicenciaOtorgada.objects.filter(pk=licencia.pk).update(grupo=grupo)


class Migration(migrations.Migration):

    dependencies = [
        ("licencias", "0011_renglon_mensual"),
    ]

    operations = [
        migrations.AddField(
            model_name="licenciaotorgada",
            name="grupo",
            field=models.UUIDField(blank=True, db_index=True, editable=False, null=True),
        ),
        migrations.RunPython(agrupar, migrations.RunPython.noop),
    ]
