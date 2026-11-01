from django.apps import apps as global_apps
from django.contrib.auth.management import create_permissions
from django.db import DEFAULT_DB_ALIAS
from django.db.models.signals import (
    post_delete,
    post_migrate,
    post_save,
    pre_delete,
    pre_save,
)
from django.dispatch import receiver

from asistencias.models import EventoAsistencia
from licencias.models import LicenciaArticulo, LicenciaOtorgada
from personal.models import Cargo, Carrera, EspacioCurricular

from .auditoria import a_json, foto_en_base
from .roles import crear_grupos
from .usuario_actual import obtener_usuario_actual


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


# ───────────── Auditoría de licencias y catálogos (RF-20) ─────────────
#
# Cada alta, modificación y baja de una licencia otorgada o de un catálogo
# deja un evento en la bitácora única (EventoAsistencia) con el usuario de la
# petición, ya venga de una vista o del admin. El evento se crea dentro de la
# misma transacción que el cambio: si el cambio se revierte, el evento también.

Accion = EventoAsistencia.Accion

_AUDITADOS = {
    LicenciaOtorgada: (Accion.LICENCIA_ALTA, Accion.LICENCIA_EDITAR, Accion.LICENCIA_BAJA),
    LicenciaArticulo: (Accion.CATALOGO_ALTA, Accion.CATALOGO_EDITAR, Accion.CATALOGO_BAJA),
    Cargo: (Accion.CATALOGO_ALTA, Accion.CATALOGO_EDITAR, Accion.CATALOGO_BAJA),
    Carrera: (Accion.CATALOGO_ALTA, Accion.CATALOGO_EDITAR, Accion.CATALOGO_BAJA),
    EspacioCurricular: (Accion.CATALOGO_ALTA, Accion.CATALOGO_EDITAR, Accion.CATALOGO_BAJA),
}


def _campos_ignorados(modelo):
    """Campos que cambian solos (auto_now) y no son una modificación real."""
    return {
        f.attname
        for f in modelo._meta.concrete_fields
        if getattr(f, "auto_now", False) or getattr(f, "auto_now_add", False)
    }


def _con_datos_de_licencia(valores):
    """Agrega DNI, docente y artículo para que la bitácora se pueda leer y filtrar."""
    if not valores:
        return valores
    from personal.models import Designacion

    designacion = (
        Designacion.objects.select_related("persona")
        .filter(pk=valores.get("designacion_id"))
        .first()
    )
    articulo = LicenciaArticulo.objects.filter(pk=valores.get("articulo_id")).first()
    extra = {}
    if designacion:
        extra["dni"] = designacion.persona.dni
        extra["docente"] = designacion.persona.apellido_nombre
    if articulo:
        extra["articulo"] = articulo.articulo
    return {**valores, **extra}


def _foto(modelo, pk):
    valores = foto_en_base(modelo, pk)
    if valores is not None:
        for campo in _campos_ignorados(modelo):
            valores.pop(campo, None)
        if modelo is LicenciaOtorgada:
            valores = _con_datos_de_licencia(valores)
    return valores


def _descripcion(instancia):
    try:
        if isinstance(instancia, LicenciaOtorgada):
            persona = instancia.designacion.persona
            return (
                f"{persona.apellido_nombre} (DNI {persona.dni}) — "
                f"{instancia.articulo.articulo}, desde {instancia.desde:%d/%m/%Y}"
            )
        return f"{instancia._meta.verbose_name}: {instancia}"
    except Exception:  # la descripción nunca debe impedir guardar el evento
        return f"{instancia._meta.verbose_name} #{instancia.pk}"


def _registrar(instancia, accion, antes, despues):
    usuario = obtener_usuario_actual()
    EventoAsistencia.objects.create(
        usuario_id=usuario.pk if usuario else None,
        accion=accion,
        motivo=_descripcion(instancia)[:500],
        antes=antes,
        despues=despues,
    )


def _antes_de_guardar(sender, instance, raw=False, **kwargs):
    instance._auditoria_antes = (
        None if raw or instance._state.adding or instance.pk is None
        else _foto(sender, instance.pk)
    )


def _despues_de_guardar(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    alta, editar, _ = _AUDITADOS[sender]
    antes = getattr(instance, "_auditoria_antes", None)
    despues = _foto(sender, instance.pk)
    if created:
        _registrar(instance, alta, None, despues)
    elif antes != despues:
        _registrar(instance, editar, antes, despues)


def _antes_de_borrar(sender, instance, **kwargs):
    instance._auditoria_baja = _foto(sender, instance.pk)


def _despues_de_borrar(sender, instance, **kwargs):
    _, _, baja = _AUDITADOS[sender]
    antes = getattr(instance, "_auditoria_baja", None)
    if antes is None:
        antes = a_json({
            f.attname: getattr(instance, f.attname)
            for f in sender._meta.concrete_fields
        })
    _registrar(instance, baja, antes, None)


for _modelo in _AUDITADOS:
    _uid = f"auditoria_{_modelo._meta.label_lower}"
    pre_save.connect(_antes_de_guardar, sender=_modelo, dispatch_uid=f"{_uid}_pre_save")
    post_save.connect(_despues_de_guardar, sender=_modelo, dispatch_uid=f"{_uid}_post_save")
    pre_delete.connect(_antes_de_borrar, sender=_modelo, dispatch_uid=f"{_uid}_pre_delete")
    post_delete.connect(_despues_de_borrar, sender=_modelo, dispatch_uid=f"{_uid}_post_delete")
