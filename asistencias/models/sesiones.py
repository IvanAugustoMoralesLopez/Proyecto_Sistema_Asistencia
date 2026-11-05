import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class ControlConcurrencia(models.Model):
    """
    Fila única usada como mutex transaccional para limitar operadores.
    La fila con pk=1 se crea mediante una señal post_migrate.
    """
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "asistencia_control_concurrencia"


class SesionEdicion(models.Model):
    """
    Representa una sesión de edición activa.
    El token evita que una sesión libere el bloqueo de otra.
    """
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sesiones_edicion_asistencia",
    )
    creada_en = models.DateTimeField(auto_now_add=True)
    heartbeat_en = models.DateTimeField(default=timezone.now)
    expira_en = models.DateTimeField()
    activa = models.BooleanField(default=True)

    class Meta:
        db_table = "asistencia_sesion_edicion"
        indexes = [
            models.Index(
                fields=["activa", "expira_en"],
                name="ix_sesion_act_expira",
            ),
        ]

    def __str__(self):
        return f"{self.usuario} — {self.token}"
