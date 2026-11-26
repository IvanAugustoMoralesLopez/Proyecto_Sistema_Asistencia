"""
Catálogo de marcas según el Documento de Requerimientos v2.0 (RF-08).

    P   = Permiso            (computa inasistencia, pide horas y motivo)
    I   = Inasistencia
    LIC = Licencia médica o especial
    LT  = Largo tratamiento
    PR  = Presente

Hasta la migración 0010 los códigos P y PR significaban otra cosa
(P = Presente, PR = Presente retirado). Antes de cambiar el catálogo se
migran los registros ya cargados para que no cambien de significado:

    P  (Presente)           -> PR (Presente)
    PR (Presente retirado)  -> I  (Inasistencia), conservando las horas y
                               agregando una nota en las observaciones.

Además LIC y LT dejan de exigir una licencia otorgada vinculada: según
RF-09 y RF-14 la marca se asienta en la diaria al recibir el formulario y
el artículo se imputa después, en la planilla mensual.
"""

from django.db import migrations

NOTA_RETIRADO = "[Migrado: era «Presente retirado»]"

NUEVAS = {
    "P": dict(
        descripcion="Permiso",
        descripcion_simple="Permiso",
        ayuda="Faltó con permiso: presentó el formulario de solicitud. "
              "Pedí las horas que no cubrió y escribí el motivo.",
        computa_inasistencia=True,
        requiere_observacion=True,
        requiere_horas=True,
        requiere_licencia=False,
    ),
    "I": dict(
        descripcion="Inasistencia",
        descripcion_simple="Faltó",
        ayuda="No asistió. Nace como injustificada hasta que entregue el "
              "formulario en papel; entonces se cambia a Licencia o Permiso.",
        computa_inasistencia=True,
        requiere_observacion=False,
        requiere_horas=True,
        requiere_licencia=False,
    ),
    "LIC": dict(
        descripcion="Licencia médica o especial",
        descripcion_simple="Licencia",
        ayuda="Falta cubierta por una licencia: presentó el formulario. "
              "El artículo se imputa en la planilla mensual.",
        computa_inasistencia=True,
        requiere_observacion=False,
        requiere_horas=True,
        requiere_licencia=False,
    ),
    "LT": dict(
        descripcion="Largo tratamiento",
        descripcion_simple="Largo tratamiento",
        ayuda="Licencia de largo tratamiento (es un tipo de licencia médica).",
        computa_inasistencia=True,
        requiere_observacion=False,
        requiere_horas=True,
        requiere_licencia=False,
    ),
    "PR": dict(
        descripcion="Presente",
        descripcion_simple="Asistió",
        ayuda="El docente cumplió su jornada.",
        computa_inasistencia=False,
        requiere_observacion=False,
        requiere_horas=False,
        requiere_licencia=False,
    ),
}

ANTERIORES = {
    "P": dict(
        descripcion="Presente", descripcion_simple="Asistió",
        ayuda="El docente cumplió su jornada completa.",
        computa_inasistencia=False, requiere_observacion=False,
        requiere_horas=False, requiere_licencia=False,
    ),
    "I": dict(
        descripcion="Inasistencia", descripcion_simple="Faltó",
        ayuda="No asistió. Pedí las horas que no cubrió. Nace como "
              "injustificada hasta que traiga el certificado.",
        computa_inasistencia=True, requiere_observacion=False,
        requiere_horas=True, requiere_licencia=False,
    ),
    "LIC": dict(
        descripcion="Licencia", descripcion_simple="Licencia",
        ayuda="Falta cubierta por una licencia ya otorgada. Hay que elegir cuál.",
        computa_inasistencia=True, requiere_observacion=False,
        requiere_horas=True, requiere_licencia=True,
    ),
    "LT": dict(
        descripcion="Largo tratamiento", descripcion_simple="Licencia larga",
        ayuda="Licencia de largo tratamiento ya otorgada. Hay que elegir cuál.",
        computa_inasistencia=True, requiere_observacion=False,
        requiere_horas=True, requiere_licencia=True,
    ),
    "PR": dict(
        descripcion="Presente retirado", descripcion_simple="Asistió y se retiró",
        ayuda="Asistió pero no cumplió toda la jornada. CUENTA COMO "
              "INASISTENCIA: pedí las horas que no cubrió y escribí el motivo.",
        computa_inasistencia=True, requiere_observacion=True,
        requiere_horas=True, requiere_licencia=False,
    ),
}


def _aplicar(MarcaAsistencia, definiciones):
    for codigo, datos in definiciones.items():
        MarcaAsistencia.objects.update_or_create(
            codigo=codigo, defaults={**datos, "activa": True},
        )


def pasar_a_v2(apps, schema_editor):
    MarcaAsistencia = apps.get_model("asistencias", "MarcaAsistencia")
    RegistroAsistencia = apps.get_model("asistencias", "RegistroAsistencia")

    # Si falta alguna marca (base recién creada sin las anteriores) se crea.
    _aplicar(MarcaAsistencia, {
        c: d for c, d in NUEVAS.items()
        if not MarcaAsistencia.objects.filter(codigo=c).exists()
    })
    marca = {m.codigo: m for m in MarcaAsistencia.objects.all()}

    # 1) Presente retirado (PR viejo) -> Inasistencia, con nota.
    for registro in RegistroAsistencia.objects.filter(marca=marca["PR"]):
        nota = registro.observaciones or ""
        if NOTA_RETIRADO not in nota:
            nota = f"{nota} {NOTA_RETIRADO}".strip()
        registro.marca = marca["I"]
        registro.observaciones = nota
        # save() del modelo histórico: no dispara señales ni auto_now propios.
        registro.save(update_fields=["marca", "observaciones"])

    # 2) Presente (P viejo) -> PR (Presente).
    RegistroAsistencia.objects.filter(marca=marca["P"]).update(marca=marca["PR"])

    # 3) Recién ahora cambia el significado del catálogo.
    _aplicar(MarcaAsistencia, NUEVAS)


def volver_a_v1(apps, schema_editor):
    """
    Vuelve al catálogo anterior. Los «Presente» vuelven a P. Los que eran
    «Presente retirado» se reconocen por la nota; los permisos cargados con
    el catálogo nuevo no tienen equivalente y pasan a Inasistencia.
    """
    MarcaAsistencia = apps.get_model("asistencias", "MarcaAsistencia")
    RegistroAsistencia = apps.get_model("asistencias", "RegistroAsistencia")
    marca = {m.codigo: m for m in MarcaAsistencia.objects.all()}

    RegistroAsistencia.objects.filter(marca=marca["P"]).update(marca=marca["I"])
    RegistroAsistencia.objects.filter(marca=marca["PR"]).update(marca=marca["P"])
    RegistroAsistencia.objects.filter(
        marca=marca["I"], observaciones__contains=NOTA_RETIRADO,
    ).update(marca=marca["PR"])
    _aplicar(MarcaAsistencia, ANTERIORES)


class Migration(migrations.Migration):

    dependencies = [
        ("asistencias", "0010_marcas_asistio"),
    ]

    operations = [
        migrations.RunPython(pasar_a_v2, volver_a_v1),
    ]
