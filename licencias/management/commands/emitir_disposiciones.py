from django.core.management.base import BaseCommand, CommandError

from licencias.planilla_mensual import emitir_disposiciones_planilla


class Command(BaseCommand):
    help = (
        "Emite las Disposiciones Internas del mes desde la planilla mensual "
        "IL-01 / IL-02, en orden alfabético (RF-16, RN-11). El mes tiene que "
        "estar procesado."
    )

    def add_arguments(self, parser):
        parser.add_argument('anio', type=int)
        parser.add_argument('mes', type=int)

    def handle(self, *args, anio, mes, **options):
        try:
            emitidas = emitir_disposiciones_planilla(anio, mes)
        except ValueError as error:
            raise CommandError(str(error))

        for numero, renglones in emitidas:
            docente = renglones[0].designacion.persona.apellido_nombre
            self.stdout.write(
                f"Disp. {numero}/{anio}  {docente}  "
                f"{renglones[0].desde:%d/%m/%Y} al {renglones[0].hasta:%d/%m/%Y}  "
                f"({len(renglones)} materia/s)"
            )
        self.stdout.write(self.style.SUCCESS(f"Emitidas: {len(emitidas)}"))
