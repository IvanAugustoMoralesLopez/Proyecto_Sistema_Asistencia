from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import LicenciaOtorgada, RegistroBitacora 

@receiver(post_save, sender=LicenciaOtorgada)
def registrar_movimiento_licencia(sender, instance, created, **kwargs):
    tipo_accion = "ALTA" if created else "MODIFICACIÓN"
    detalle = f"{tipo_accion} - Licencia {instance.articulo.articulo} (DNI {instance.designacion.persona.dni}) desde {instance.desde}"

    RegistroBitacora.objects.create(
        accion=tipo_accion,
        descripcion=detalle
    )