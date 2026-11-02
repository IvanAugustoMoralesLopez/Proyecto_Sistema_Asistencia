from django.core.management.base import BaseCommand, CommandError

from licencias.services import emitir_disposiciones_mes


class Command(BaseCommand):
    help = "Emite las Disposiciones Internas del mes en orden alfabético (RF-16, RN-10, RN-11)."

    def add_arguments(self, parser):
        parser.add_argument('anio', type=int)
        parser.add_argument('mes', type=int)
        parser.add_argument(
            '--oficina', default=None,
            help="Código de oficina. Por defecto, el de los parámetros del sistema.",
        )

    def handle(self, *args, anio, mes, oficina, **options):
        try:
            resultado = emitir_disposiciones_mes(anio, mes, oficina)
        except ValueError as error:
            raise CommandError(str(error))

        for numero, licencia in resultado['emitidas']:
            self.stdout.write(
                f"Disp. {numero}/{anio}  {licencia.designacion.persona.apellido_nombre}  "
                f"art. {licencia.articulo.articulo}  desde {licencia.desde}"
            )
        self.stdout.write(self.style.SUCCESS(f"Emitidas: {len(resultado['emitidas'])}"))

        if resultado['omitidas']:
            self.stdout.write(self.style.WARNING(
                f"Omitidas por falta de N° de formulario en papel (RN-10): "
                f"{len(resultado['omitidas'])}"
            ))
            for licencia in resultado['omitidas']:
                self.stdout.write(
                    f"  - {licencia.designacion.persona.apellido_nombre}  "
                    f"art. {licencia.articulo.articulo}  desde {licencia.desde}"
                )