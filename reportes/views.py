import csv

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from asistencias.models import EventoAsistencia

from .auditoria import datos_usuario, registrar_evento
from .exportaciones import ENCABEZADO_LICENCIAS, filas_licencias
from .forms import (
    FiltroBitacoraForm,
    FiltroConsultaForm,
    ParametroSistemaForm,
    UsuarioForm,
)
from .models import ParametroSistema
from .roles import ROLES
from .selectors import (
    buscar_eventos,
    buscar_licencias,
    describir_objetivo,
    resumir_cambios,
    texto_instrumento,
)

User = get_user_model()


def _querystring_sin(request, *claves):
    """Parámetros GET actuales sin las claves indicadas (para paginar/exportar)."""
    parametros = request.GET.copy()
    for clave in claves:
        parametros.pop(clave, None)
    return parametros.urlencode()


# ───────────── Bitácora (RF-20) ─────────────

@login_required
@permission_required("reportes.ver_bitacora", raise_exception=True)
def bitacora(request):
    form = FiltroBitacoraForm(request.GET or None)
    filtros = form.cleaned_data if form.is_valid() else {}

    pagina = Paginator(buscar_eventos(filtros), 25).get_page(request.GET.get("page"))
    for evento in pagina:
        evento.objetivo = describir_objetivo(evento)
        evento.cambios = resumir_cambios(evento)

    return render(
        request,
        "reportes/bitacora.html",
        {"form": form, "pagina": pagina, "querystring": _querystring_sin(request, "page")},
    )


# ───────────── Parámetros (RF-21) ─────────────

@login_required
@permission_required("reportes.gestionar_parametros", raise_exception=True)
def parametros(request):
    campos = ("codigo_oficina", "nombre_oficina", "ciclo_lectivo")
    instancia = ParametroSistema.obtener()
    # Foto previa: is_valid() ya modifica la instancia en memoria.
    antes = {c: getattr(instancia, c) for c in campos}
    form = ParametroSistemaForm(request.POST or None, instance=instancia)

    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            parametro = form.save(commit=False)
            parametro.actualizado_por = request.user
            parametro.save()
            registrar_evento(
                request.user,
                EventoAsistencia.Accion.PARAMETROS,
                antes=antes,
                despues={c: getattr(parametro, c) for c in campos},
            )
        messages.success(request, "Parámetros actualizados.")
        return redirect("reportes:parametros")

    return render(
        request,
        "reportes/parametros.html",
        {"form": form, "parametro": instancia},
    )


# ───────────── Usuarios y roles (RF-19) ─────────────

def _rol_de(usuario):
    return next((g.name for g in usuario.groups.all() if g.name in ROLES), "Sin rol")


@login_required
@permission_required("reportes.gestionar_usuarios", raise_exception=True)
def usuarios(request):
    texto = request.GET.get("q", "").strip()
    rol = request.GET.get("rol", "").strip()

    lista = User.objects.prefetch_related("groups").order_by("username")
    if texto:
        lista = lista.filter(
            Q(username__icontains=texto)
            | Q(first_name__icontains=texto)
            | Q(last_name__icontains=texto)
        )
    if rol in ROLES:
        lista = lista.filter(groups__name=rol)

    for usuario in lista:
        usuario.rol = _rol_de(usuario)

    return render(
        request,
        "reportes/usuarios.html",
        {"usuarios": lista, "q": texto, "rol": rol, "roles": ROLES},
    )


@login_required
@permission_required("reportes.gestionar_usuarios", raise_exception=True)
def usuario_crear(request):
    form = UsuarioForm(request.POST or None, usuario_actual=request.user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            nuevo = form.save()
            registrar_evento(
                request.user,
                EventoAsistencia.Accion.USUARIO_ALTA,
                despues=datos_usuario(nuevo, form.cleaned_data["rol"].name),
            )
        messages.success(request, f"Usuario «{nuevo.username}» creado.")
        return redirect("reportes:usuarios")
    return render(request, "reportes/usuario_form.html", {"form": form, "titulo": "Nuevo usuario"})


@login_required
@permission_required("reportes.gestionar_usuarios", raise_exception=True)
def usuario_editar(request, pk):
    objetivo = get_object_or_404(User, pk=pk)
    # Un superusuario solo lo puede tocar otro superusuario.
    if objetivo.is_superuser and not request.user.is_superuser:
        raise PermissionDenied

    # Foto previa: is_valid() ya modifica la instancia en memoria.
    antes = datos_usuario(objetivo, _rol_de(objetivo))
    form = UsuarioForm(request.POST or None, instance=objetivo, usuario_actual=request.user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            objetivo.refresh_from_db()
            despues = datos_usuario(objetivo, form.cleaned_data["rol"].name)
            if form.cleaned_data.get("password1"):
                despues["contraseña"] = "restablecida"  # nunca el valor
            registrar_evento(
                request.user,
                EventoAsistencia.Accion.USUARIO_EDITAR,
                antes=antes,
                despues=despues,
            )
        messages.success(request, f"Usuario «{objetivo.username}» actualizado.")
        return redirect("reportes:usuarios")
    return render(
        request,
        "reportes/usuario_form.html",
        {"form": form, "titulo": f"Editar usuario: {objetivo.username}"},
    )


# ───────────── Consultas (RF-17) ─────────────

@login_required
@permission_required("reportes.consultar_licencias", raise_exception=True)
def consultas(request):
    form = FiltroConsultaForm(request.GET or None)
    licencias = buscar_licencias(form.cleaned_data if form.is_valid() else {})

    if form.is_valid() and request.GET.get("exportar") == "csv":
        respuesta = HttpResponse(content_type="text/csv; charset=utf-8")
        respuesta["Content-Disposition"] = 'attachment; filename="consulta_licencias.csv"'
        respuesta.write("\ufeff")  # para que Excel respete los acentos
        escritor = csv.writer(respuesta)
        escritor.writerow(ENCABEZADO_LICENCIAS)
        escritor.writerows(filas_licencias(licencias))
        return respuesta

    pagina = Paginator(licencias, 25).get_page(request.GET.get("page"))
    for lic in pagina:
        lic.instrumento = texto_instrumento(lic)

    return render(
        request,
        "reportes/consultas.html",
        {
            "form": form,
            "pagina": pagina,
            "querystring": _querystring_sin(request, "page", "exportar"),
        },
    )
