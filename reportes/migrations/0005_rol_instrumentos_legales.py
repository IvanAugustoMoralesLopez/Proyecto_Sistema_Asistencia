from django.contrib.auth.management import create_permissions
from django.db import migrations

ROLES = ("Bedelía", "Secretaría", "Subsecretaría")
PERMISOS = ("add_tipoinstrumentolegal", "change_tipoinstrumentolegal")


def dar_permisos_de_instrumentos(apps, schema_editor):
    """
    RF-05: los tres roles administran el catálogo de tipos de instrumento
    legal. `crear_grupos` no toca los grupos que ya existen, así que en una
    base ya creada los permisos nuevos se agregan acá. En una base nueva los
    grupos todavía no existen: los crea post_migrate con la matriz completa.
    """
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    grupos = list(Group.objects.filter(name__in=ROLES))
    if not grupos:
        return

    # Los permisos de un modelo nuevo se crean recién en post_migrate: se
    # generan ahora para poder asignarlos.
    config = apps.get_app_config("personal")
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)
    config.models_module = None

    permisos = list(
        Permission.objects.filter(
            content_type__app_label="personal",
            codename__in=PERMISOS,
        )
    )
    for grupo in grupos:
        grupo.permissions.add(*permisos)


class Migration(migrations.Migration):

    dependencies = [
        ("reportes", "0004_rol_calendario_escolar"),
        ("personal", "0004_instrumentos_legales_y_sin_inicio"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(dar_permisos_de_instrumentos, migrations.RunPython.noop),
    ]
