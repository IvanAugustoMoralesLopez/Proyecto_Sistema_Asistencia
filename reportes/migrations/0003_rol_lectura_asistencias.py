from django.db import migrations

ROLES = ("Bedelía", "Secretaría", "Subsecretaría")


def dar_lectura_de_asistencias(apps, schema_editor):
    """
    M5: los tres roles pasan a tener el permiso de lectura de asistencias.

    `crear_grupos` no toca los grupos que ya existen, así que las bases ya
    creadas no recibirían el permiso nuevo de reportes/roles.py. En una base
    nueva los grupos todavía no existen acá: los crea post_migrate con la
    matriz completa.
    """
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    permiso = Permission.objects.filter(
        content_type__app_label="asistencias",
        codename="view_registroasistencia",
    ).first()
    if permiso is None:
        return
    for grupo in Group.objects.filter(name__in=ROLES):
        grupo.permissions.add(permiso)


class Migration(migrations.Migration):

    dependencies = [
        ("reportes", "0002_alter_parametrosistema_options"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(dar_lectura_de_asistencias, migrations.RunPython.noop),
    ]
