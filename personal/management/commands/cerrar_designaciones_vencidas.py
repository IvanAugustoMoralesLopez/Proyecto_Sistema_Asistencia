from django.core.management.base import BaseCommand
from django.utils import timezone

from personal.models import Designacion


class Command(BaseCommand):
    help = (
        "Da de baja las designaciones vencidas y registra cada cese en el historial. "
        "Programar su ejecución diaria."
    )

    def handle(self, *args, **options):
        hoy = timezone.localdate()
        vencidas = Designacion.objects.filter(
            activo=True,
            hasta__lt=hoy,
        )
        cerradas = 0
        for designacion in vencidas.iterator():
            designacion.activo = False
            designacion.save(update_fields=["activo"])
            cerradas += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Designaciones vencidas dadas de baja: {cerradas}."
            )
        )
