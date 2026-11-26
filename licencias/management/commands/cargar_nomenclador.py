from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from licencias.nomenclador import (
    RUTA_CSV,
    cargar_nomenclador,
    leer_nomenclador,
    reemplazar_inventados as reemplazar_articulos_de_prueba,
)


class Command(BaseCommand):
    help = (
        "Carga o actualiza el catálogo de artículos con el Nomenclador de "
        "Licencias oficial (licencias/data/nomenclador.csv). Se puede correr "
        "las veces que haga falta: crea los códigos nuevos y actualiza los que "
        "cambiaron."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--archivo", default=str(RUTA_CSV),
            help="CSV a cargar (por defecto, el del repositorio).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Muestra qué haría, sin guardar nada.",
        )
        parser.add_argument(
            "--reemplazar-inventados", action="store_true",
            help=(
                "Además, pasa las licencias que usan los artículos de prueba "
                "(T-14, T-15, T-20, T-22, T-25) a los del nomenclador y los borra. "
                "Sin --confirmar solo muestra qué cambiaría."
            ),
        )
        parser.add_argument(
            "--confirmar", action="store_true",
            help="Aplica el reemplazo de --reemplazar-inventados.",
        )

    def handle(self, *args, archivo, dry_run, reemplazar_inventados, confirmar, **options):
        try:
            filas = leer_nomenclador(archivo)
        except FileNotFoundError:
            raise CommandError(f"No existe el archivo {archivo}.")
        except ValidationError as error:
            raise CommandError("El nomenclador tiene errores:\n  " + "\n  ".join(error.messages))

        resultado = cargar_nomenclador(filas, guardar=not dry_run)
        prefijo = "[prueba] " if dry_run else ""
        self.stdout.write(
            f"{prefijo}Nomenclador: {len(resultado.creados)} nuevos, "
            f"{len(resultado.actualizados)} actualizados, "
            f"{len(resultado.sin_cambios)} sin cambios."
        )
        if resultado.actualizados:
            self.stdout.write("  Actualizados: " + ", ".join(resultado.actualizados))

        if not reemplazar_inventados:
            if not dry_run:
                self.stdout.write(self.style.SUCCESS("Listo."))
            return

        if dry_run and confirmar:
            raise CommandError("--dry-run y --confirmar no van juntos.")
        if dry_run:
            self.stdout.write(
                "El reemplazo de los artículos de prueba necesita el nomenclador "
                "cargado: corré el comando sin --dry-run primero."
            )
            return

        cambio = reemplazar_articulos_de_prueba(guardar=confirmar)
        titulo = "Reemplazo de artículos de prueba" + ("" if confirmar else " (vista previa, no se guardó nada)")
        self.stdout.write(titulo + ":")
        for tipo, pk, de, a, docente in cambio.cambios:
            self.stdout.write(f"  {tipo} {pk}: {docente}  {de} → {a}")
        for tipo, pk, de, situacion, docente in cambio.sin_equivalente:
            self.stdout.write(self.style.WARNING(
                f"  {tipo} {pk}: {docente}  {de} sin equivalente para {situacion or 'sin situación'}: queda como está"
            ))
        if cambio.borrados:
            verbo = "Borrados" if confirmar else "Se borrarían"
            self.stdout.write(f"  {verbo}: {', '.join(cambio.borrados)}")

        if confirmar:
            self.stdout.write(self.style.SUCCESS(f"Listo: {len(cambio.cambios)} cambios."))
        else:
            self.stdout.write("Para aplicarlo: agregá --confirmar.")
