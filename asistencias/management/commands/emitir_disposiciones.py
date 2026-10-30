from django.core.management.base import BaseCommand, CommandError

from licencias.services import OFICINA_DEFAULT, emitir_disposiciones_mes


class Command(BaseCommand):
    help = "Emite las Disposiciones Internas del mes en orden alfabético (RF-16, RN-10, RN-11)."

    def add_arguments(self, parser):
        parser.add_argument('anio', type=int)
        parser.add_argument('mes', type=int)
        parser.add_argument('--oficina', default=OFICINA_DEFAULT)

    def handle(self, *args, anio, mes, oficina, **options):
        if not 1 <= mes <= 12:
            raise CommandError("El mes debe estar entre 1 y 12.")

        resultado = emitir_disposiciones_mes(anio, mes, oficina)

        for numero, lic in resultado['emitidas']:
            persona = lic.designacion.persona
            self.stdout.write(
                f"Disp. {numero}/{anio}  {persona.apellido}, {persona.nombre}  "
                f"art. {lic.articulo.articulo}  desde {lic.desde}"
            )
        self.stdout.write(self.style.SUCCESS(f"Emitidas: {len(resultado['emitidas'])}"))

        if resultado['omitidas']:
            self.stdout.write(self.style.WARNING(
                f"Omitidas por falta de N° de formulario en papel (RN-10): "
                f"{len(resultado['omitidas'])}"
            ))
            for lic in resultado['omitidas']:
                persona = lic.designacion.persona
                self.stdout.write(
                    f"  - {persona.apellido}, {persona.nombre}  "
                    f"art. {lic.articulo.articulo}  desde {lic.desde}"
                )
