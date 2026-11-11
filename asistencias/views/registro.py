"""
Registro diario (consulta por fecha), alta/edición individual de una
asistencia, historial con filtros y validación de registros.
"""

import csv

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from licencias.models import LicenciaOtorgada
from personal.models import Designacion

from ..forms import FiltroAsistenciaForm, RegistroAsistenciaForm
from ..models import CierreDiario, CierreMensual, EventoAsistencia, RegistroAsistencia
from ..services import (
    clave_dia,
    conteo_del_dia,
    dia_habil_mas_cercano,
    guardar_asistencia,
    horario_del_dia,
    horas_del_dia,
    motivo_dia_no_laborable,
    validar_asistencia,
    validar_multiples,
)
from ._comun import (
    _aplicar_filtros,
    _asegurar_sesion_edicion,
    contexto_sesion,
    _dia_vecino,
    _fecha_pedida,
    _id_pedido,
    _ids_pedidos,
    _mensaje_error,
    _paginar,
    _url_segura,
    vista_protegida,
)


@vista_protegida("asistencias.view_registroasistencia")
def registro_diario(request):
    hoy = timezone.localdate()
    fecha_objeto = _fecha_pedida(request.GET.get("fecha"), por_defecto=hoy)

    if fecha_objeto is None:
        messages.error(request, "La fecha seleccionada no es válida.")
        return redirect("asistencia:registro_diario")

    registros = list(
        RegistroAsistencia.objects.select_related(
            "designacion__persona",
            "designacion__cargo",
            "designacion__espacio_curricular__carrera",
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
        and fecha_objeto <= hoy
    )

    total = len(registros)
    presentes = sum(
        1 for r in registros if not r.marca.computa_inasistencia
    )
    inasistencias = total - presentes
    sin_validar = sum(
        1 for r in registros
        if r.estado_registro == RegistroAsistencia.Estado.BORRADOR
    )
    pendientes_formulario = sum(
        1 for r in registros
        if r.estado_justificacion
        in (
            RegistroAsistencia.EstadoJustificacion.INJUSTIFICADA,
            RegistroAsistencia.EstadoJustificacion.EN_TRAMITE,
        )
    )

    fecha_anterior = _dia_vecino(fecha_objeto, -1).isoformat()
    fecha_siguiente = _dia_vecino(fecha_objeto, 1).isoformat()

    # Punto 6: si la fecha no es hábil, ofrecer el día en el que sí se carga,
    # en vez de dejar al operador frente a un aviso sin salida.
    dia_habil_sugerido = (
        dia_habil_mas_cercano(fecha_objeto, sentido=-1)
        if motivo_no_laborable
        else None
    )

    # Cuantos docentes corresponden a esta fecha y cuantos faltan cargar: es
    # lo que permite que la pantalla proponga la accion en vez de limitarse a
    # mostrar una tabla vacia.
    conteo = (
        conteo_del_dia(fecha_objeto)
        if not motivo_no_laborable
        else {"total": 0, "cargados": 0, "pendientes": 0}
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
            "total": total,
            "presentes": presentes,
            "inasistencias": inasistencias,
            "sin_validar": sin_validar,
            "pendientes_formulario": pendientes_formulario,
            "fecha_anterior": fecha_anterior,
            "fecha_siguiente": fecha_siguiente,
            "dia_habil_sugerido": dia_habil_sugerido,
            "es_hoy": fecha_objeto == hoy,
            "total_del_dia": conteo["total"],
            "cargados_del_dia": conteo["cargados"],
            "faltan_cargar": conteo["pendientes"],
            "periodo_cerrado": periodo_cerrado,
            **contexto_sesion(request),
        },
    )


@vista_protegida("asistencias.add_registroasistencia", methods=["GET", "POST"])
def crear_asistencia(request):
    fecha_inicial = request.GET.get("fecha")

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
        hoy = timezone.localdate()
        form = RegistroAsistenciaForm(
            initial={"fecha": _fecha_pedida(fecha_inicial, por_defecto=hoy) or hoy}
        )

    return render(
        request,
        "asistencias/formulario_asistencia.html",
        {
            "form": form,
            "titulo": "Registrar asistencia",
            "url_cancelar": reverse("asistencia:historial"),
        },
    )


@vista_protegida("asistencias.change_registroasistencia", methods=["GET", "POST"])
def editar_asistencia(request, pk):
    registro = get_object_or_404(
        RegistroAsistencia.objects.select_related(
            "designacion",
            "marca",
            "licencia",
        ),
        pk=pk,
    )

    volver = _url_segura(
        request.GET.get("volver", request.POST.get("volver", ""))
    )

    if request.method == "POST":
        form = RegistroAsistenciaForm(
            request.POST,
            instance=registro,
        )

        if form.is_valid():
            try:
                token = _asegurar_sesion_edicion(request)
                guardar_asistencia(
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
                if volver:
                    return redirect(volver)
                return redirect(
                    f"{reverse('asistencia:registro_diario')}"
                    f"?fecha={registro.fecha.isoformat()}"
                )
    else:
        form = RegistroAsistenciaForm(instance=registro)

    return render(
        request,
        "asistencias/formulario_asistencia.html",
        {
            "form": form,
            "registro": registro,
            "titulo": "Editar asistencia",
            "volver": volver,
            "url_cancelar": volver or reverse("asistencia:historial"),
        },
    )


@vista_protegida("asistencias.view_registroasistencia")
def datos_designacion(request):
    """
    Datos que el alta individual puede completar sola (JSON).

    Dada una designación y una fecha devuelve las horas cátedra que el
    docente tiene ese día de la semana y las licencias otorgadas que cubren
    la fecha, para que el operador no tenga que buscarlas ni escribirlas.
    Es solo lectura: no crea ni modifica nada.
    """
    designacion_id = _id_pedido(request.GET.get("designacion"))
    fecha = _fecha_pedida(request.GET.get("fecha"))

    if designacion_id is None or fecha is None:
        return JsonResponse(
            {"error": "Indicá una designación y una fecha válidas."},
            status=400,
        )

    designacion = (
        Designacion.objects.filter(pk=designacion_id)
        .select_related("persona")
        .prefetch_related("horarios")
        .first()
    )

    if designacion is None:
        return JsonResponse({"error": "La designación no existe."}, status=404)

    horas = horas_del_dia(designacion, fecha)
    horario = horario_del_dia(designacion, fecha)
    licencias = (
        LicenciaOtorgada.objects.select_related("articulo")
        .filter(designacion=designacion, desde__lte=fecha)
        .filter(Q(hasta__isnull=True) | Q(hasta__gte=fecha))
        .order_by("desde", "pk")
    )

    return JsonResponse({
        "dia": clave_dia(fecha),
        "tiene_clase": horario is not None,
        "horas_dia": str(horas),
        "hora_inicio": (
            horario.hora_inicio.strftime("%H:%M")
            if horario and horario.hora_inicio
            else ""
        ),
        "hora_fin": (
            horario.hora_fin.strftime("%H:%M")
            if horario and horario.hora_fin
            else ""
        ),
        "motivo_no_laborable": motivo_dia_no_laborable(fecha) or "",
        "licencias": [
            {
                "id": licencia.pk,
                "texto": (
                    f"{licencia.articulo.articulo} · "
                    f"{licencia.articulo.tipo_licencia}"
                ),
            }
            for licencia in licencias
        ],
    })


@vista_protegida("asistencias.view_registroasistencia")
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


@vista_protegida("asistencias.view_registroasistencia")
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

    volver = _url_segura(request.GET.get("desde", ""))

    return render(
        request,
        "asistencias/detalle_asistencia.html",
        {
            "registro": registro,
            "eventos": eventos,
            "volver": volver,
        },
    )


@vista_protegida("asistencias.validar_registro", methods=["POST"])
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

    destino = _url_segura(request.POST.get("next", ""))
    return redirect(destino or "asistencia:historial")


@vista_protegida("asistencias.validar_registro", methods=["POST"])
def validar_multiples_view(request):
    ids_validos = _ids_pedidos(request.POST.getlist("registro_ids"))

    if not ids_validos:
        messages.warning(request, "No seleccionaste ningún registro.")
        return redirect("asistencia:historial")

    try:
        token = _asegurar_sesion_edicion(request)
        validados = validar_multiples(
            usuario=request.user,
            token=token,
            registro_ids=ids_validos,
        )
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, _mensaje_error(exc))
    else:
        omitidos = len(ids_validos) - validados
        if omitidos:
            messages.success(
                request,
                f"Se validaron {validados} registro(s). "
                f"{omitidos} ya estaba(n) validado(s).",
            )
        else:
            messages.success(
                request,
                f"Se validaron {validados} registro(s).",
            )

    destino = _url_segura(request.POST.get("next", ""))
    return redirect(destino or "asistencia:historial")


@vista_protegida("asistencias.view_registroasistencia")
def exportar_csv(request):
    form = FiltroAsistenciaForm(request.GET or None)

    registros = (
        RegistroAsistencia.objects.select_related(
            "designacion__persona",
            "designacion__cargo",
            "designacion__espacio_curricular",
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

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="asistencias.csv"'
    response.write("﻿")

    # Excel en español espera «;» como separador: con «,» vuelca todo en una
    # sola columna y hay que importar a mano (punto 19).
    writer = csv.writer(response, delimiter=";")
    writer.writerow([
        "Fecha",
        "DNI",
        "Docente",
        "Cargo",
        "Espacio curricular",
        "Marca",
        "Horas",
        "Estado",
        "Justificación",
        "N° formulario",
        "Actualizado por",
    ])

    limite = 5000
    total_registros = registros.count()

    for r in registros[:limite]:
        writer.writerow([
            r.fecha.strftime("%d/%m/%Y"),
            r.designacion.persona.dni,
            r.designacion.persona.apellido_nombre,
            r.designacion.cargo.descripcion,
            (
                r.designacion.espacio_curricular.nombre
                if r.designacion.espacio_curricular
                else ""
            ),
            r.marca.codigo,
            r.horas_inasistidas,
            r.get_estado_registro_display(),
            r.get_estado_justificacion_display(),
            r.nro_formulario,
            str(r.actualizado_por or ""),
        ])

    if total_registros > limite:
        writer.writerow([
            f"*** Exportación limitada a {limite} de "
            f"{total_registros} registros ***",
        ])

    return response
