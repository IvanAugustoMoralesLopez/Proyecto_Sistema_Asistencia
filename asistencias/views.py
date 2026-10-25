
import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from licencias.models import LicenciaOtorgada
from personal.models import Designacion

from .forms import (
    RegistroAsistenciaForm,
    FiltroAsistenciaForm,
    FiltroRecepcionForm,
    RecepcionFormularioForm,
    CierreMensualForm,
    ReaperturaMensualForm,
)
from .models import (
    RegistroAsistencia,
    CierreDiario,
    CierreMensual,
    EventoAsistencia,
    MarcaAsistencia,
    licencia_cubre_fecha,
)
from .services import (
    PlanillaConErrores,
    adquirir_sesion_edicion,
    renovar_sesion_edicion,
    liberar_sesion_edicion,
    guardar_asistencia,
    guardar_planilla,
    recepcionar_formulario,
    validar_asistencia,
    cerrar_dia,
    cerrar_mes,
    reabrir_mes,
    motivo_dia_no_laborable,
)


def _token_edicion(request):
    token = request.session.get("asistencia_token")

    if not token:
        token = str(uuid.uuid4())
        request.session["asistencia_token"] = token

    return token


def _asegurar_sesion_edicion(request):
    token = _token_edicion(request)
    adquirir_sesion_edicion(request.user, token)
    return token


def _mensaje_error(exc):
    """
    Texto legible de una excepción esperada. str() de una ValidationError
    devuelve la representación de la lista o del diccionario de errores.
    """
    if isinstance(exc, ValidationError):
        return " ".join(exc.messages)

    return str(exc)


@login_required
def registro_diario(request):
    fecha_seleccionada = request.GET.get(
        "fecha",
        date.today().isoformat(),
    )

    try:
        fecha_objeto = date.fromisoformat(fecha_seleccionada)
    except ValueError:
        messages.error(request, "La fecha seleccionada no es válida.")
        return redirect("asistencia:registro_diario")

    form = FiltroAsistenciaForm(
        initial={
            "desde": fecha_seleccionada,
            "hasta": fecha_seleccionada,
        }
    )

    registros = (
        RegistroAsistencia.objects.select_related(
            "designacion__persona",
            "designacion__cargo",
            "designacion__espacio_curricular",
            "marca",
            "licencia",
        )
        .filter(fecha=fecha_objeto)
        .order_by(
            "designacion__persona__apellido_nombre",
            "designacion_id",
        )
    )

    cierre = CierreMensual.objects.filter(
        anio=fecha_objeto.year,
        mes=fecha_objeto.month,
    ).first()
    jornada_cerrada = (
        CierreDiario.objects.select_related("cerrado_por")
        .filter(fecha=fecha_objeto)
        .first()
    )
    motivo_no_laborable = motivo_dia_no_laborable(fecha_objeto)
    periodo_cerrado = bool(
        cierre and cierre.estado == CierreMensual.Estado.CERRADO
    )

    puede_cerrar_jornada = (
        request.user.has_perm("asistencias.cerrar_jornada")
        and jornada_cerrada is None
        and not motivo_no_laborable
        and not periodo_cerrado
        and fecha_objeto <= timezone.localdate()
    )

    return render(
        request,
        "asistencias/registro_diario.html",
        {
            "registros": registros,
            "fecha_seleccionada": fecha_objeto.isoformat(),
            "cierre": cierre,
            "jornada_cerrada": jornada_cerrada,
            "puede_cerrar_jornada": puede_cerrar_jornada,
            "motivo_no_laborable": motivo_no_laborable,
            "form": form,
        },
    )


def _designaciones_del_dia(fecha, texto=""):
    """Designaciones vigentes en la fecha, ordenadas por docente."""
    designaciones = (
        Designacion.objects.filter(
            activo=True,
            persona__activa=True,
            desde__lte=fecha,
        )
        .filter(Q(hasta__isnull=True) | Q(hasta__gte=fecha))
        .select_related("persona", "cargo", "espacio_curricular")
        .order_by("persona__apellido_nombre", "persona_id", "id")
    )

    if texto:
        designaciones = designaciones.filter(
            Q(persona__apellido_nombre__icontains=texto)
            | Q(persona__dni__icontains=texto)
        )

    return designaciones


def _armar_filas(fecha, texto, valores, errores):
    """Una fila por designación vigente, con lo ya cargado y lo enviado."""
    designaciones = list(_designaciones_del_dia(fecha, texto))
    ids = [designacion.pk for designacion in designaciones]

    existentes = {
        registro.designacion_id: registro
        for registro in RegistroAsistencia.objects.select_related(
            "marca"
        ).filter(fecha=fecha, designacion_id__in=ids)
    }

    licencias = defaultdict(list)
    vigentes = (
        LicenciaOtorgada.objects.select_related("articulo")
        .filter(designacion_id__in=ids, desde__lte=fecha)
        .filter(Q(hasta__isnull=True) | Q(hasta__gte=fecha))
    )

    for licencia in vigentes:
        licencias[licencia.designacion_id].append(licencia)

    filas = []
    docente_anterior = None

    for designacion in designaciones:
        filas.append(
            {
                "designacion": designacion,
                "registro": existentes.get(designacion.pk),
                "licencias": licencias.get(designacion.pk, []),
                "valores": valores.get(designacion.pk, {}),
                "error": errores.get(designacion.pk),
                "primera_del_docente": (
                    designacion.persona_id != docente_anterior
                ),
            }
        )
        docente_anterior = designacion.persona_id

    return filas


def _leer_planilla(post, fecha):
    """
    Interpreta lo enviado por la planilla. Devuelve las filas listas para
    guardar, los valores enviados (para volver a mostrarlos) y los errores
    por designación.
    """
    prefijo = "marca-"
    ids = sorted(
        int(clave[len(prefijo):])
        for clave in post
        if clave.startswith(prefijo)
        and clave[len(prefijo):].isdigit()
        and post[clave]
    )

    designaciones = {
        designacion.pk: designacion
        for designacion in _designaciones_del_dia(fecha).filter(pk__in=ids)
    }
    marcas = {marca.pk: marca for marca in MarcaAsistencia.vigentes()}

    filas = []
    valores = {}
    errores = {}

    for pk in ids:
        marca_texto = post.get(f"marca-{pk}", "")
        horas_texto = post.get(f"horas-{pk}", "").strip()
        licencia_texto = post.get(f"licencia-{pk}", "")
        observaciones = post.get(f"obs-{pk}", "").strip()

        valores[pk] = {
            "marca": marca_texto,
            "horas": horas_texto,
            "licencia": licencia_texto,
            "obs": observaciones,
        }

        designacion = designaciones.get(pk)

        if designacion is None:
            errores[pk] = "La designación no está vigente en esta fecha."
            continue

        marca = marcas.get(int(marca_texto)) if marca_texto.isdigit() else None

        if marca is None:
            errores[pk] = "La marca elegida no es válida."
            continue

        try:
            horas = (
                Decimal(horas_texto.replace(",", "."))
                if horas_texto
                else Decimal("0")
            )
        except InvalidOperation:
            horas = None

        if horas is None or not horas.is_finite() or horas < 0:
            errores[pk] = "Las horas deben ser un número mayor o igual a cero."
            continue

        licencia = None

        if licencia_texto:
            licencia = (
                LicenciaOtorgada.objects.filter(
                    pk=int(licencia_texto), designacion=designacion
                ).first()
                if licencia_texto.isdigit()
                else None
            )

            if licencia is None or not licencia_cubre_fecha(licencia, fecha):
                errores[pk] = "La licencia elegida no es válida para esta fecha."
                continue

        filas.append(
            {
                "designacion": designacion,
                "marca": marca,
                "horas_inasistidas": horas,
                "licencia": licencia,
                "observaciones": observaciones,
            }
        )

    return filas, valores, errores


@login_required
@permission_required(
    "asistencias.add_registroasistencia",
    raise_exception=True,
)
@require_http_methods(["GET", "POST"])
def planilla_rapida(request):
    """Planilla de marcado del día: una fila por designación vigente."""
    origen = request.POST if request.method == "POST" else request.GET

    try:
        fecha = date.fromisoformat(
            origen.get("fecha", timezone.localdate().isoformat())
        )
    except ValueError:
        messages.error(request, "La fecha seleccionada no es válida.")
        return redirect("asistencia:planilla_rapida")

    texto = origen.get("q", "").strip()

    cierre = CierreMensual.objects.filter(
        anio=fecha.year,
        mes=fecha.month,
    ).first()
    jornada_cerrada = (
        CierreDiario.objects.select_related("cerrado_por")
        .filter(fecha=fecha)
        .first()
    )
    motivo_no_laborable = motivo_dia_no_laborable(fecha)
    puede_modificar_cerrada = request.user.has_perm(
        "asistencias.modificar_jornada_cerrada"
    )

    # Motivo por el que la planilla no se puede guardar, si lo hay.
    if fecha > timezone.localdate():
        bloqueo = "No se puede registrar asistencia de una fecha futura."
    elif motivo_no_laborable:
        bloqueo = f"{motivo_no_laborable}: no corresponde registrar asistencia."
    elif cierre and cierre.estado == CierreMensual.Estado.CERRADO:
        bloqueo = "El período está cerrado. Solicitá una reapertura autorizada."
    elif jornada_cerrada and not puede_modificar_cerrada:
        bloqueo = (
            "La jornada está cerrada: modificarla requiere autorización "
            "de Secretaría o Subsecretaría."
        )
    else:
        bloqueo = None

    valores = {}
    errores = {}

    if request.method == "POST":
        if bloqueo:
            messages.error(request, bloqueo)
        else:
            filas, valores, errores = _leer_planilla(request.POST, fecha)

            if errores:
                messages.error(
                    request,
                    "Corregí las filas marcadas. No se guardó ninguna.",
                )
            else:
                try:
                    token = _asegurar_sesion_edicion(request)
                    registros = guardar_planilla(
                        usuario=request.user,
                        token=token,
                        fecha=fecha,
                        filas=filas,
                        motivo=request.POST.get("motivo", ""),
                    )
                except PlanillaConErrores as exc:
                    errores = exc.errores
                    messages.error(
                        request,
                        "Corregí las filas marcadas. No se guardó ninguna.",
                    )
                except (ValidationError, PermissionDenied) as exc:
                    messages.error(request, _mensaje_error(exc))
                else:
                    messages.success(
                        request,
                        f"Se registraron {len(registros)} asistencias.",
                    )
                    return redirect(
                        f"{reverse('asistencia:registro_diario')}"
                        f"?fecha={fecha.isoformat()}"
                    )

    filas = _armar_filas(fecha, texto, valores, errores)
    marcadas = sum(1 for fila in filas if fila["registro"])

    return render(
        request,
        "asistencias/planilla_rapida.html",
        {
            "fecha": fecha,
            "fecha_texto": fecha.isoformat(),
            "texto": texto,
            "filas": filas,
            "marcas": MarcaAsistencia.vigentes(),
            "marca_presente": MarcaAsistencia.vigentes()
            .filter(codigo="P")
            .first(),
            "bloqueo": bloqueo,
            "jornada_cerrada": jornada_cerrada,
            "total": len(filas),
            "marcadas": marcadas,
            "pendientes": len(filas) - marcadas,
        },
    )


@login_required
@permission_required(
    "asistencias.cerrar_jornada",
    raise_exception=True,
)
@require_POST
def cerrar_jornada(request):
    try:
        fecha = date.fromisoformat(request.POST.get("fecha", ""))
    except ValueError:
        messages.error(request, "La fecha seleccionada no es válida.")
        return redirect("asistencia:registro_diario")

    try:
        token = _asegurar_sesion_edicion(request)
        cerrar_dia(usuario=request.user, token=token, fecha=fecha)
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _mensaje_error(exc))
    else:
        messages.success(
            request,
            f"Se cerró la jornada del {fecha:%d/%m/%Y}.",
        )

    return redirect(
        f"{reverse('asistencia:registro_diario')}"
        f"?fecha={fecha.isoformat()}"
    )


@login_required
@permission_required(
    "asistencias.add_registroasistencia",
    raise_exception=True,
)
@require_http_methods(["GET", "POST"])
def crear_asistencia(request):
    if request.method == "POST":
        form = RegistroAsistenciaForm(request.POST)

        if form.is_valid():
            try:
                token = _asegurar_sesion_edicion(request)
                registro = guardar_asistencia(
                    usuario=request.user,
                    token=token,
                    datos=form.cleaned_data,
                    motivo=request.POST.get("motivo", ""),
                )
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _mensaje_error(exc))
            else:
                messages.success(
                    request,
                    "La asistencia se guardó correctamente.",
                )
                return redirect(
                    f"{reverse('asistencia:registro_diario')}"
                    f"?fecha={registro.fecha.isoformat()}"
                )
    else:
        form = RegistroAsistenciaForm(
            initial={"fecha": date.today()}
        )

    return render(
        request,
        "asistencias/formulario_asistencia.html",
        {
            "form": form,
            "titulo": "Registrar asistencia",
        },
    )


@login_required
@permission_required(
    "asistencias.change_registroasistencia",
    raise_exception=True,
)
@require_http_methods(["GET", "POST"])
def editar_asistencia(request, pk):
    registro = get_object_or_404(
        RegistroAsistencia.objects.select_related(
            "designacion",
            "marca",
            "licencia",
        ),
        pk=pk,
    )

    if request.method == "POST":
        form = RegistroAsistenciaForm(
            request.POST,
            instance=registro,
        )

        if form.is_valid():
            try:
                token = _asegurar_sesion_edicion(request)
                actualizado = guardar_asistencia(
                    usuario=request.user,
                    token=token,
                    datos=form.cleaned_data,
                    registro_id=registro.pk,
                    motivo=request.POST.get("motivo", ""),
                )
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _mensaje_error(exc))
            else:
                messages.success(
                    request,
                    "La asistencia se actualizó correctamente.",
                )
                return redirect("asistencia:historial")
    else:
        form = RegistroAsistenciaForm(instance=registro)

    return render(
        request,
        "asistencias/formulario_asistencia.html",
        {
            "form": form,
            "registro": registro,
            "titulo": "Editar asistencia",
        },
    )


def _aplicar_filtros(registros, datos):
    """Filtros comunes del historial y de la recepción de formularios."""
    if datos.get("dni"):
        registros = registros.filter(
            designacion__persona__dni__icontains=datos["dni"]
        )

    if datos.get("apellido_nombre"):
        registros = registros.filter(
            designacion__persona__apellido_nombre__icontains=(
                datos["apellido_nombre"]
            )
        )

    if datos.get("desde"):
        registros = registros.filter(fecha__gte=datos["desde"])

    if datos.get("hasta"):
        registros = registros.filter(fecha__lte=datos["hasta"])

    if datos.get("marca"):
        registros = registros.filter(marca=datos["marca"])

    return registros


def _paginar(request, registros):
    paginador = Paginator(registros, 25)
    pagina = paginador.get_page(request.GET.get("page"))

    # Los enlaces de paginación conservan los filtros aplicados.
    parametros = request.GET.copy()
    parametros.pop("page", None)

    return pagina, parametros.urlencode()


@login_required
def historial(request):
    form = FiltroAsistenciaForm(request.GET or None)

    registros = (
        RegistroAsistencia.objects.select_related(
            "designacion__persona",
            "designacion__cargo",
            "marca",
            "actualizado_por",
        )
        .all()
        .order_by("-fecha", "designacion__persona__apellido_nombre")
    )

    if form.is_valid():
        datos = form.cleaned_data
        registros = _aplicar_filtros(registros, datos)

        if datos.get("estado_justificacion"):
            registros = registros.filter(
                estado_justificacion=datos["estado_justificacion"]
            )

    pagina, querystring = _paginar(request, registros)

    return render(
        request,
        "asistencias/historial.html",
        {
            "form": form,
            "pagina": pagina,
            "querystring": querystring,
        },
    )


@login_required
def detalle_asistencia(request, pk):
    registro = get_object_or_404(
        RegistroAsistencia.objects.select_related(
            "designacion__persona",
            "designacion__cargo",
            "marca",
            "licencia",
            "creado_por",
            "actualizado_por",
        ),
        pk=pk,
    )

    eventos = EventoAsistencia.objects.filter(
        asistencia=registro,
    ).select_related("usuario")

    return render(
        request,
        "asistencias/detalle_asistencia.html",
        {
            "registro": registro,
            "eventos": eventos,
        },
    )


@login_required
@permission_required(
    "asistencias.validar_registro",
    raise_exception=True,
)
@require_POST
def validar_registro(request, pk):
    try:
        token = _asegurar_sesion_edicion(request)
        validar_asistencia(
            usuario=request.user,
            token=token,
            registro_id=pk,
        )
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _mensaje_error(exc))
    else:
        messages.success(request, "El registro quedó validado.")

    return redirect("asistencia:historial")


@login_required
def recepcion_formularios(request):
    """Inasistencias a la espera de formulario en papel (RF-09)."""
    form = FiltroRecepcionForm(request.GET or None)
    Justificacion = RegistroAsistencia.EstadoJustificacion

    registros = (
        RegistroAsistencia.objects.select_related(
            "designacion__persona",
            "designacion__cargo",
            "designacion__espacio_curricular",
            "marca",
            "recepcionado_por",
        )
        .filter(marca__computa_inasistencia=True)
        .order_by("-fecha", "designacion__persona__apellido_nombre")
    )

    estado = FiltroRecepcionForm.PENDIENTES

    if form.is_valid():
        datos = form.cleaned_data
        registros = _aplicar_filtros(registros, datos)
        estado = (
            datos.get("estado_justificacion")
            or FiltroRecepcionForm.PENDIENTES
        )

    if estado == FiltroRecepcionForm.PENDIENTES:
        registros = registros.filter(
            estado_justificacion__in=[
                Justificacion.INJUSTIFICADA,
                Justificacion.EN_TRAMITE,
            ]
        )
    elif estado != FiltroRecepcionForm.TODAS:
        registros = registros.filter(estado_justificacion=estado)

    pagina, querystring = _paginar(request, registros)

    return render(
        request,
        "asistencias/recepcion_formularios.html",
        {
            "form": form,
            "pagina": pagina,
            "querystring": querystring,
        },
    )


@login_required
@permission_required(
    "asistencias.recepcionar_formulario",
    raise_exception=True,
)
@require_http_methods(["GET", "POST"])
def recepcionar_formulario_view(request, pk):
    registro = get_object_or_404(
        RegistroAsistencia.objects.select_related(
            "designacion__persona",
            "designacion__cargo",
            "marca",
            "recepcionado_por",
        ),
        pk=pk,
    )

    if request.method == "POST":
        form = RecepcionFormularioForm(request.POST, registro=registro)

        if form.is_valid():
            datos = form.cleaned_data

            try:
                token = _asegurar_sesion_edicion(request)
                recepcionar_formulario(
                    usuario=request.user,
                    token=token,
                    registro_id=registro.pk,
                    nuevo_estado=datos["estado_justificacion"],
                    nro_formulario=datos["nro_formulario"],
                    fecha_recepcion=datos["fecha_recepcion"],
                    motivo=datos["motivo"],
                )
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _mensaje_error(exc))
            else:
                messages.success(
                    request,
                    "El estado de la inasistencia se actualizó.",
                )
                return redirect("asistencia:recepcion_formularios")
    else:
        form = RecepcionFormularioForm(registro=registro)

    return render(
        request,
        "asistencias/recepcionar_formulario.html",
        {
            "form": form,
            "registro": registro,
            "puede_recepcionar": bool(form.fields["estado_justificacion"].choices),
        },
    )


@login_required
def lista_cierres(request):
    cierres = CierreMensual.objects.select_related(
        "cerrado_por",
        "reabierto_por",
    ).all()
    cierres_diarios = CierreDiario.objects.select_related("cerrado_por")[:15]

    return render(
        request,
        "asistencias/cierres.html",
        {"cierres": cierres, "cierres_diarios": cierres_diarios},
    )


@login_required
@permission_required(
    "asistencias.cerrar_periodo",
    raise_exception=True,
)
@require_http_methods(["GET", "POST"])
def confirmar_cierre(request):
    if request.method == "POST":
        form = CierreMensualForm(request.POST)

        if form.is_valid():
            try:
                token = _asegurar_sesion_edicion(request)
                cierre = cerrar_mes(
                    usuario=request.user,
                    token=token,
                    anio=form.cleaned_data["anio"],
                    mes=form.cleaned_data["mes"],
                )
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _mensaje_error(exc))
            else:
                messages.success(
                    request,
                    f"Se cerró el período {cierre.anio}-{cierre.mes:02d}.",
                )
                return redirect("asistencia:lista_cierres")
    else:
        hoy = date.today()
        form = CierreMensualForm(
            initial={"anio": hoy.year, "mes": hoy.month}
        )

    return render(
        request,
        "asistencias/confirmar_cierre.html",
        {"form": form},
    )


@login_required
@permission_required(
    "asistencias.change_cierremensual",
    raise_exception=True,
)
@require_http_methods(["GET", "POST"])
def reapertura_mensual(request, anio, mes):
    cierre = get_object_or_404(
        CierreMensual,
        anio=anio,
        mes=mes,
    )

    if request.method == "POST":
        form = ReaperturaMensualForm(request.POST)

        if form.is_valid():
            try:
                token = _asegurar_sesion_edicion(request)
                reabrir_mes(
                    usuario=request.user,
                    token=token,
                    anio=anio,
                    mes=mes,
                    motivo=form.cleaned_data["motivo"],
                )
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, _mensaje_error(exc))
            else:
                messages.success(
                    request,
                    "El período fue reabierto.",
                )
                return redirect("asistencia:lista_cierres")
    else:
        form = ReaperturaMensualForm()

    return render(
        request,
        "asistencias/reapertura_mensual.html",
        {
            "form": form,
            "cierre": cierre,
        },
    )


@login_required
@require_POST
def liberar_edicion(request):
    token = request.session.get("asistencia_token")

    if token:
        liberar_sesion_edicion(request.user, token)
        request.session.pop("asistencia_token", None)

    messages.info(request, "Se liberó la sesión de edición.")
    return redirect("asistencia:registro_diario")


@login_required
@require_POST
def renovar_edicion(request):
    token = request.session.get("asistencia_token")

    try:
        renovar_sesion_edicion(request.user, token)
    except (ValidationError, PermissionDenied) as exc:
        return render(
            request,
            "asistencias/error_sesion.html",
            {"mensaje": _mensaje_error(exc)},
            status=409,
        )

    return redirect("asistencia:registro_diario")
