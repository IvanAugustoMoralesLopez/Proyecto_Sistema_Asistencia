from django.db import migrations

ROLES = ("Bedelia","Secretaría", "Subsecretaría")
PERMISOS = ("add_dianolaborable", "change_dianolaborable", "delete_dianolaborable")


def dar_permisos_de_calendario(apps, schema_editor):
    """
    RF-10:Bedelia Secretaría y Subsecretaría pasan a administrar el calendario escolar.

    `crear_grupos` no modifica los grupos que ya existen, así que las bases ya
    creadas no recibirían los permisos nuevos de reportes/roles.py. En una base
    nueva los grupos todavía no existen acá: los crea post_migrate con la
    matriz completa.
    """
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    permisos = list(
        Permission.objects.filter(
            content_type__app_label="asistencias",
            codename__in=PERMISOS,
        )
    )
    if not permisos:
        return
    for grupo in Group.objects.filter(name__in=ROLES):
        grupo.permissions.add(*permisos)


class Migration(migrations.Migration):

    dependencies = [
        ("reportes", "0003_rol_lectura_asistencias"),
        ("asistencias", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(dar_permisos_de_calendario, migrations.RunPython.noop),
    ]
