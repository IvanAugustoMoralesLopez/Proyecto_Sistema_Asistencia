from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import (
    Persona,
    Cargo,
    Carrera,
    EspacioCurricular,
    Designacion,
)


class DesignacionTests(TestCase):
    def setUp(self):
        self.persona = Persona.objects.create(
            dni="30123456",
            apellido_nombre="Docente de prueba",
        )
        self.cargo = Cargo.objects.create(
            codigo="PROF",
            descripcion="Profesor",
        )

    def test_crear_designacion(self):
        designacion = Designacion.objects.create(
            persona=self.persona,
            cargo=self.cargo,
            desde=date(2026, 3, 1),
        )
        self.assertEqual(
            designacion.persona.apellido_nombre,
            "Docente de prueba",
        )

    def test_fecha_final_no_puede_ser_anterior(self):
        designacion = Designacion(
            persona=self.persona,
            cargo=self.cargo,
            desde=date(2026, 3, 10),
            hasta=date(2026, 3, 1),
        )
        with self.assertRaises(ValidationError):
            designacion.full_clean()