from django.apps import apps as global_apps
from django.contrib.auth.management import create_permissions
from django.db import DEFAULT_DB_ALIAS
from django.db.models.signals import post_migrate, pre_delete, pre_save
from django.dispatch import receiver

from asistencias.models import EventoAsistencia

from .roles import crear_grupos


class BitacoraInalterable(Exception):
    """Se intentó modificar o borrar un registro de la bitácora (RF-20)."""


@receiver(post_migrate)
def crear_roles(sender, **kwargs):
    """Crea los grupos Bedelía / Secretaría / Subsecretaría."""
    if sender.label != "reportes":
        return

    using = kwargs.get("using", DEFAULT_DB_ALIAS)

    # Los permisos se crean en su propio post_migrate; los generamos acá
    # para no depender del orden en que se ejecutan las señales.
    for label in ("asistencias", "reportes", "personal", "licencias"):
        create_permissions(
            global_apps.get_app_config(label),
            verbosity=0,
            using=using,
        )

    crear_grupos(using)


@receiver(pre_save, sender=EventoAsistencia)
def impedir_edicion_de_eventos(sender, instance, raw=False, **kwargs):
    if not raw and not instance._state.adding:
        raise BitacoraInalterable("Los eventos de la bitácora no se pueden modificar.")


@receiver(pre_delete, sender=EventoAsistencia)
def impedir_borrado_de_eventos(sender, instance, **kwargs):
    raise BitacoraInalterable("Los eventos de la bitácora no se pueden borrar.")
