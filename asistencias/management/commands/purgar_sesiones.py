from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from asistencias.models import SesionEdicion


class Command(BaseCommand):
    help = "Elimina sesiones de edición inactivas con más de 30 días."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dias",
            type=int,
            default=30,
            help="Antigüedad mínima en días (por defecto 30).",
        )

    def handle(self, *args, **options):
        dias = options["dias"]
        limite = timezone.now() - timedelta(days=dias)
        eliminadas, _ = SesionEdicion.objects.filter(
            activa=False,
            expira_en__lt=limite,
        ).delete()
        self.stdout.write(f"Se eliminaron {eliminadas} sesiones inactivas.")
