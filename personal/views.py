import csv
import io
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from reportes.auditoria import AccionesReportes, registrar_evento

from .forms import (
    BuscarLegajoForm,
    CarreraForm,
    CargoForm,
    DesignacionForm,
    EspacioCurricularForm,
    NuevaDesignacionForm,
    PersonaForm,
)
from .models import (
    Cargo,
    Carrera,
    Designacion,
    EspacioCurricular,
    ImportacionPersonalError,
    Persona,
)
from licencias.models import LicenciaArticulo
from licencias.forms import LicenciaArticuloForm

MAX_CSV_BYTES = 5 * 1024 * 1024


def _mensaje_errores(exc):
    if isinstance(exc, ValidationError):
        if hasattr(exc, "message_dict"):
            return "; ".join(
                f"{campo}: {', '.join(errores)}"
                for campo, errores in exc.message_dict.items()
            )
        return "; ".join(exc.messages)
    return str(exc)


def _importar_fila_personal(fila):
    dni = (fila.get("dni") or "").strip()
    if not dni:
        raise ValidationError("Falta el DNI.")

    persona = Persona.objects.filter(pk=dni).first()
    apellido_nombre = (fila.get("apellido_nombre") or "").strip()
    apellido = (fila.get("apellido") or "").strip()
    nombres = (fila.get("nombres") or "").strip()
    if not apellido_nombre and not (apellido or nombres):
        if persona is None:
            raise ValidationError(
                "El DNI no existe y la fila no contiene datos personales para crearlo."
            )
    else:
        persona = persona or Persona(dni=dni)
        apellido_actual = (fila.get("apellido") or "").strip() if "apellido" in fila else persona.apellido
        nombres_actuales = (fila.get("nombres") or "").strip() if "nombres" in fila else persona.nombres
        if apellido_nombre:
            persona.apellido_nombre = apellido_nombre
        elif "apellido" in fila or "nombres" in fila:
            persona.apellido_nombre = ", ".join(
                parte for parte in (apellido_actual, nombres_actuales) if parte
            )
        for campo in (
            "apellido",
            "nombres",
            "sexo",
            "telefono",
            "email",
            "localidad",
            "domicilio_calle",
        ):
            if campo in fila:
                setattr(persona, campo, (fila.get(campo) or "").strip())
        persona.full_clean()
        persona.save()

    codigo_cargo = (fila.get("cargo_codigo") or "").strip()
    if not codigo_cargo:
        return

    cargo = Cargo.objects.filter(pk=codigo_cargo).first()
    if cargo is None:
        raise ValidationError(f"No existe el cargo '{codigo_cargo}'.")

    espacio_nombre = (fila.get("espacio_curricular") or "").strip()
    espacio = None
    if espacio_nombre:
        espacio = EspacioCurricular.objects.filter(
            nombre__iexact=espacio_nombre,
            activo=True,
        ).first()
        if espacio is None:
            raise ValidationError(
                f"No existe el espacio curricular '{espacio_nombre}'."
            )

    fecha_inicio = (fila.get("desde") or "").strip()
    try:
        desde = date.fromisoformat(fecha_inicio)
    except ValueError as exc:
        raise ValidationError(
            "La fecha 'desde' debe tener formato AAAA-MM-DD."
        ) from exc

    situacion = (fila.get("situacion_revista") or "").strip().upper()
    situacion = {
        "TITULAR": Designacion.Situacion.TITULAR,
        "INTERINO": Designacion.Situacion.INTERINO,
        "SUPLENTE": Designacion.Situacion.SUPLENTE,
    }.get(situacion, situacion)
    designacion = Designacion(
        persona=persona,
        cargo=cargo,
        espacio_curricular=espacio,
        situacion_revista=situacion,
        norma_tipo=(fila.get("norma_tipo") or "").strip(),
        norma_numero=(fila.get("norma_numero") or "").strip(),
        organismo_emisor=(fila.get("organismo_emisor") or "").strip(),
        desde=desde,
    )
    fecha_fin = (fila.get("hasta") or "").strip()
    if fecha_fin:
        try:
            designacion.hasta = date.fromisoformat(fecha_fin)
        except ValueError as exc:
            raise ValidationError(
                "La fecha 'hasta' debe tener formato AAAA-MM-DD."
            ) from exc

    designacion.full_clean()
    if Designacion.objects.filter(
        persona=persona,
        cargo=cargo,
        espacio_curricular=espacio,
        situacion_revista=designacion.situacion_revista,
        desde=designacion.desde,
        hasta=designacion.hasta,
    ).exists():
        raise ValidationError(
            "La fila duplica una designación ya registrada para el docente."
        )
    designacion.save()


def _procesar_csv(archivo):
    if archivo.size > MAX_CSV_BYTES:
        raise ValidationError("El archivo CSV supera el máximo de 5 MB.")
    if not archivo.name.lower().endswith(".csv"):
        raise ValidationError("El archivo seleccionado debe tener extensión .csv.")

    try:
        contenido = archivo.read().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError("El archivo debe estar codificado en UTF-8.") from exc

    lector = csv.DictReader(io.StringIO(contenido))
    if not lector.fieldnames:
        raise ValidationError("El CSV debe incluir una fila de encabezados.")
    lector.fieldnames = [nombre.strip().lower() for nombre in lector.fieldnames]
    if "dni" not in lector.fieldnames:
        raise ValidationError("El CSV debe incluir una columna 'dni'.")

    total = 0
    rechazadas = 0
    for numero_fila, fila in enumerate(lector, start=2):
        total += 1
        try:
            with transaction.atomic():
                _importar_fila_personal(fila)
        except (ValidationError, IntegrityError, ValueError) as exc:
            rechazadas += 1
            ImportacionPersonalError.objects.create(
                archivo=archivo.name[:255],
                numero_fila=numero_fila,
                dni_texto=(fila.get("dni") or "")[:20],
                motivo_error=_mensaje_errores(exc)[:255],
                fila_original=fila,
            )

    return total, rechazadas


@login_required
@permission_required("personal.change_persona", raise_exception=True)
@require_http_methods(["GET", "POST"])
def gestion_legajos(request):
    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "importar_csv":
            if not request.user.has_perm("personal.change_persona"):
                raise PermissionDenied
            archivo = request.FILES.get("archivo")
            if not archivo:
                messages.error(request, "Seleccione un archivo CSV.")
            else:
                try:
                    total, rechazadas = _procesar_csv(archivo)
                except ValidationError as exc:
                    messages.error(request, _mensaje_errores(exc))
                else:
                    registrar_evento(
                        request.user,
                        AccionesReportes.IMPORTACION,
                        motivo=f"Archivo {archivo.name}"[:500],
                        despues={
                            "filas": total,
                            "importadas": total - rechazadas,
                            "rechazadas": rechazadas,
                        },
                    )
                    messages.success(
                        request,
                        f"Importación finalizada: {total - rechazadas} filas "
                        f"importadas y {rechazadas} rechazadas.",
                    )
            return redirect(reverse("personal:gestion_legajos"))

        if accion == "guardar_persona":
            dni = request.POST.get("dni", "").strip()
            persona_existente = Persona.objects.filter(pk=dni).first()
            form = PersonaForm(request.POST, instance=persona_existente)
            if form.is_valid():
                persona = form.save()
                messages.success(request, "El legajo se guardó correctamente.")
                return redirect(
                    f"{reverse('personal:gestion_legajos')}?dni={persona.pk}"
                )
            messages.error(request, "Revise los datos personales indicados.")
            return render(
                request,
                "personal/gestion_legajos.html",
                _contexto_pantalla(request, form=form, persona=persona_existente),
            )

        if accion in {"guardar_designacion", "dar_baja_designacion"}:
            if not request.user.has_perm("personal.change_designacion"):
                raise PermissionDenied
            dni = request.POST.get("dni", "").strip()
            persona = get_object_or_404(Persona, pk=dni)
            designacion_id = request.POST.get("designacion_id")
            designacion = None
            if designacion_id:
                designacion = get_object_or_404(
                    Designacion,
                    pk=designacion_id,
                    persona=persona,
                )

            if accion == "dar_baja_designacion":
                if designacion and designacion.activo:
                    designacion.activo = False
                    designacion.save()
                    messages.success(
                        request,
                        "La designación se dio de baja y se conservó en el historial.",
                    )
                return redirect(
                    f"{reverse('personal:gestion_legajos')}?dni={persona.pk}"
                )

            form = DesignacionForm(request.POST, instance=designacion)
            if form.is_valid():
                form.instance.persona = persona
                designacion = form.save()
                messages.success(request, "La designación se guardó correctamente.")
                return redirect(
                    f"{reverse('personal:gestion_legajos')}?dni={persona.pk}"
                )
            messages.error(request, "Revise los datos de la designación.")
            return render(
                request,
                "personal/gestion_legajos.html",
                _contexto_pantalla(
                    request,
                    persona=persona,
                    designacion_form=form,
                    designacion_seleccionada=designacion,
                ),
            )

        messages.error(request, "La acción solicitada no es válida.")
        return redirect(reverse("personal:gestion_legajos"))

    filtro = BuscarLegajoForm(request.GET or None)
    dni = (request.GET.get("dni") or "").strip()
    persona = Persona.objects.filter(pk=dni).first() if dni else None
    designacion_id = request.GET.get("designacion")
    designacion = None
    if persona and designacion_id:
        designacion = Designacion.objects.filter(
            pk=designacion_id,
            persona=persona,
        ).first()

    return render(
        request,
        "personal/gestion_legajos.html",
        _contexto_pantalla(
            request,
            filtro=filtro,
            persona=persona,
            designacion_seleccionada=designacion,
        ),
    )


def _contexto_pantalla(
    request,
    *,
    filtro=None,
    form=None,
    persona=None,
    designacion_form=None,
    designacion_seleccionada=None,
):
    filtro = filtro or BuscarLegajoForm(request.GET or None)
    if form is None:
        form = PersonaForm(instance=persona)
    if designacion_form is None:
        designacion_form = DesignacionForm(instance=designacion_seleccionada)

    resultados = Designacion.objects.select_related(
        "persona",
        "cargo",
        "espacio_curricular",
        "espacio_curricular__carrera",
    ).order_by("persona__apellido_nombre", "desde")
    if not persona:
        resultados = resultados.filter(activo=True)
    if filtro.is_valid():
        dni_filtro = filtro.cleaned_data.get("dni")
        cargo = filtro.cleaned_data.get("cargo")
        espacio = filtro.cleaned_data.get("espacio_curricular")
        if dni_filtro:
            resultados = resultados.filter(persona__dni__icontains=dni_filtro)
        if cargo:
            resultados = resultados.filter(cargo=cargo)
        if espacio:
            resultados = resultados.filter(espacio_curricular=espacio)

    if persona:
        designaciones = persona.designaciones.select_related(
            "cargo",
            "espacio_curricular",
            "espacio_curricular__carrera",
        ).prefetch_related("horarios", "historial")
    else:
        designaciones = Designacion.objects.none()

    return {
        "filtro": filtro,
        "persona_form": form,
        "designacion_form": designacion_form,
        "persona": persona,
        "designacion_seleccionada": designacion_seleccionada,
        "designaciones": designaciones,
        "resultados": resultados,
        "cargos": Cargo.objects.filter(activo=True).order_by("descripcion"),
        "espacios": EspacioCurricular.objects.filter(activo=True)
        .select_related("carrera")
        .order_by("carrera__nombre", "nombre"),
        "errores_importacion": ImportacionPersonalError.objects.all()[:10],
        "licencias_admin_url": "/admin/licencias/licenciaarticulo/",
    }


@login_required
@permission_required("personal.change_designacion", raise_exception=True)
def registro_designaciones(request):
    consulta = request.GET.get("q", "").strip()
    situacion = request.GET.get("sit_revista", "").strip()
    designaciones = (
        Designacion.objects.select_related(
            "persona",
            "cargo",
            "espacio_curricular",
        )
        .prefetch_related("horarios")
        .order_by("persona__apellido_nombre", "desde", "pk")
    )
    if consulta:
        designaciones = designaciones.filter(
            Q(persona__dni__icontains=consulta)
            | Q(persona__apellido_nombre__icontains=consulta)
            | Q(cargo__codigo__icontains=consulta)
            | Q(cargo__descripcion__icontains=consulta)
            | Q(espacio_curricular__nombre__icontains=consulta)
            | Q(espacio_curricular__carrera__nombre__icontains=consulta)
        )
    if situacion:
        designaciones = designaciones.filter(situacion_revista=situacion)

    for designacion in designaciones:
        designacion.horas_por_dia = {
            horario.dia: horario.horas_catedra
            for horario in designacion.horarios.all()
        }

    return render(
        request,
        "pantallas/datos_personal.html",
        {
            "designaciones": designaciones,
            "consulta": consulta,
        },
    )


@login_required
def catalogos_personal(request):
    configuracion = {
        "cargos": {
            "titulo": "Cargos",
            "modelo": Cargo,
            "form": CargoForm,
            "campo_activo": "activo",
        },
        "carreras": {
            "titulo": "Carreras",
            "modelo": Carrera,
            "form": CarreraForm,
            "campo_activo": "activa",
        },
        "espacios": {
            "titulo": "Espacios curriculares",
            "modelo": EspacioCurricular,
            "form": EspacioCurricularForm,
            "campo_activo": "activo",
        },
        "licencias": {
            "titulo": "Tipos de licencia",
            "modelo": LicenciaArticulo,
            "form": LicenciaArticuloForm,
            "campo_activo": None,
        },
    }
    seccion = request.GET.get("seccion", "cargos")
    if seccion not in configuracion:
        seccion = "cargos"
    permisos_seccion = {
        "cargos": "personal.change_cargo",
        "carreras": "personal.change_carrera",
        "espacios": "personal.change_espaciocurricular",
        "licencias": "licencias.change_licenciaarticulo",
    }
    if not request.user.has_perm(permisos_seccion[seccion]):
        raise PermissionDenied

    datos = configuracion[seccion]
    objeto_id = request.GET.get("editar")
    objeto = datos["modelo"].objects.filter(pk=objeto_id).first() if objeto_id else None
    if objeto_id and objeto is None:
        messages.error(request, "El registro solicitado no existe.")
        return redirect(f"{reverse('personal:catalogos')}?seccion={seccion}")

    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "guardar":
            objeto = datos["modelo"].objects.filter(pk=request.POST.get("objeto_id")).first()
            objeto_id_enviado = (request.POST.get("objeto_id") or "").strip()
            if objeto_id_enviado and objeto is None:
                messages.error(request, "El registro solicitado no existe.")
                return redirect(f"{reverse('personal:catalogos')}?seccion={seccion}")
            form = datos["form"](request.POST, instance=objeto)
            if form.is_valid():
                try:
                    with transaction.atomic():
                        form.save()
                except IntegrityError:
                    messages.error(
                        request,
                        "No se pudo guardar: ya existe otro registro con esos datos.",
                    )
                except (ProtectedError, ValidationError):
                    messages.error(
                        request,
                        "No se pudo guardar el registro por datos relacionados.",
                    )
                else:
                    messages.success(request, f"{datos['titulo']} guardado correctamente.")
                    return redirect(f"{reverse('personal:catalogos')}?seccion={seccion}")
        elif accion == "eliminar":
            objeto = datos["modelo"].objects.filter(pk=request.POST.get("objeto_id")).first()
            if objeto:
                campo_activo = datos["campo_activo"]
                if campo_activo:
                    setattr(objeto, campo_activo, False)
                    objeto.save(update_fields=[campo_activo])
                    messages.success(request, "El catálogo se desactivó correctamente.")
                else:
                    try:
                        objeto.delete()
                    except ProtectedError:
                        messages.error(
                            request,
                            "El registro está en uso y no puede eliminarse.",
                        )
                    else:
                        messages.success(request, "El registro se eliminó correctamente.")
                return redirect(f"{reverse('personal:catalogos')}?seccion={seccion}")
            messages.error(request, "El registro solicitado no existe.")
            return redirect(f"{reverse('personal:catalogos')}?seccion={seccion}")
        else:
            form = datos["form"](request.POST)
    else:
        form = datos["form"](instance=objeto) if objeto else datos["form"]()

    if request.method == "POST" and accion == "guardar" and not form.is_valid():
        messages.error(request, "Revise los datos ingresados.")

    return render(
        request,
        "personal/catalogos.html",
        {
            "seccion": seccion,
            "configuracion": configuracion,
            "titulo": datos["titulo"],
            "form": form,
            "objeto": objeto,
            "registros": datos["modelo"].objects.all().order_by("pk"),
        },
    )


@login_required
@permission_required("personal.change_designacion", raise_exception=True)
@require_http_methods(["GET", "POST"])
def nueva_designacion(request):
    if request.method == "POST":
        form = NuevaDesignacionForm(request.POST)
        if form.is_valid():
            designacion = form.save()
            messages.success(
                request,
                "La designación docente se guardó correctamente.",
            )
            return redirect(reverse("inicio_personal"))
        messages.error(request, "Revise los datos de la designación.")
    else:
        inicial = {}
        dni = request.GET.get("dni", "").strip()
        if dni and Persona.objects.filter(pk=dni, activa=True).exists():
            inicial["persona"] = dni
        form = NuevaDesignacionForm(initial=inicial)

    return render(
        request,
        "personal/nueva_designacion.html",
        {"form": form},
    )
