from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .forms import BuscarLegajoForm, LegajoDocenteForm
from .models import Cargo, Designacion, EspacioCurricular


@login_required
def gestion_legajos(request):
    filtro = BuscarLegajoForm(request.GET or None)
    docente_form = LegajoDocenteForm(initial={"dni": "", "nombre_docente": ""})

    resultados = (
        Designacion.objects.select_related(
            "persona",
            "cargo",
            "espacio_curricular",
        )
        .filter(activo=True)
        .order_by("persona__apellido_nombre", "desde")
    )

    if filtro.is_valid():
        dni = filtro.cleaned_data.get("dni")
        cargo = filtro.cleaned_data.get("cargo")
        espacio = filtro.cleaned_data.get("espacio_curricular")

        if dni:
            resultados = resultados.filter(persona__dni__icontains=dni)
        if cargo:
            resultados = resultados.filter(cargo=cargo)
        if espacio:
            resultados = resultados.filter(espacio_curricular=espacio)

    cargos = Cargo.objects.filter(activo=True).order_by("descripcion")
    espacios = EspacioCurricular.objects.filter(activo=True).select_related("carrera").order_by("carrera__nombre", "nombre")

    return render(
        request,
        "personal/gestion_legajos.html",
        {
            "filtro": filtro,
            "docente_form": docente_form,
            "resultados": resultados,
            "cargos": cargos,
            "espacios": espacios,
        },
    )
