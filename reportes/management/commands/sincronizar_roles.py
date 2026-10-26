from django.core.management.base import BaseCommand

from reportes.roles import restablecer_grupos


class Command(BaseCommand):
    help = (
        "Restablece los permisos de Bedelía, Secretaría y Subsecretaría a los "
        "valores por defecto (pisa los cambios hechos a mano en esos grupos)."
    )

    def handle(self, *args, **options):
        restablecer_grupos()
        self.stdout.write(self.style.SUCCESS("Roles sincronizados."))
