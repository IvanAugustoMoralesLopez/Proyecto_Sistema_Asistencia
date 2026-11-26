"""
Planilla rápida: carga de todas las marcas del día en una sola pantalla
(RF-07).

RF-07 (documento v2.0): la novedad se registra UNA SOLA VEZ POR AGENTE y
jornada, sin discriminar materias. La pantalla muestra una fila por docente
(`_agrupar_por_agente`); al guardar, `_leer_agentes` reparte esa única marca
entre las designaciones que el docente tiene ese día, con las horas de cada
una según su horario. El desglose por materia lo hace el sistema, no quien
carga: la base sigue guardando un registro por designación, que es lo que
después necesita la planilla mensual (RF-12).

La planilla se arma sola con lo que ya está cargado en el sistema y el
operador solo confirma o corrige las excepciones:

- muestra, por defecto, solo las designaciones que tienen clase ese día
  según el horario cargado en Personal (`personal.Horario`);
- propone «Presente» en cada fila pendiente;
- completa las horas de la fila con las horas cátedra que el docente tiene
  ese día de la semana, así no hay que escribirlas;
- si el docente tiene una licencia otorgada que cubre la fecha, propone la
  marca de licencia y la licencia ya elegida;
- permite traer lo cargado el día hábil anterior como punto de partida.

Nada de esto guarda por su cuenta: son valores propuestos en el formulario
que el operador revisa antes de «Guardar planilla».
"""

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from licencias.models import LicenciaOtorgada

from ..models import (
    CierreDiario,
    CierreMensual,
    MarcaAsistencia,
    RegistroAsistencia,
    licencia_cubre_fecha,
)
from ..services import (
    PlanillaConErrores,
    aviso_del_calendario,
    ciclo_lectivo_actual,
    designaciones_del_dia as _designaciones_del_dia,
    dia_habil_mas_cercano,
    dias_con_clase,
    guardar_planilla,
    horario_del_dia,
    horas_del_dia,
    licencias_por_designacion,
    motivo_dia_no_laborable,
)
from ._comun import (
    _asegurar_sesion_edicion,
    _dia_vecino,
    _fecha_pedida,
    _id_pedido,
    _mensaje_error,
    contexto_sesion,
    vista_protegida,
)

# Valores del selector «a quiénes mostrar».
ALCANCE_CON_CLASE = "clase"
ALCANCE_TODOS = "todos"

# Marcas que se proponen automáticamente.
CODIGO_PRESENTE = "PR"
CODIGO_LICENCIA = "LIC"
CODIGO_LARGO_TRATAMIENTO = "LT"
TEXTO_LARGO_TRATAMIENTO = "largo tratamiento"


def _licencias_vigentes(ids, fecha):
    """Licencias otorgadas que cubren la fecha, agrupadas por designación."""
    vigentes = (
        LicenciaOtorgada.objects.select_related("articulo")
        .filter(designacion_id__in=ids, desde__lte=fecha)
        .filter(Q(hasta__isnull=True) | Q(hasta__gte=fecha))
        .order_by("desde", "pk")
    )
    return licencias_por_designacion(vigentes)


def _marca_de_licencia(licencia, marcas):
    """Marca que corresponde a la licencia: LT si es de largo tratamiento."""
    tipo = (licencia.articulo.tipo_licencia or "").lower()
    codigo = (
        CODIGO_LARGO_TRATAMIENTO
        if TEXTO_LARGO_TRATAMIENTO in tipo
        else CODIGO_LICENCIA
    )
    return marcas.get(codigo) or marcas.get(CODIGO_LICENCIA)


def _sugerir(licencias, marcas, horas):
    """
    Valores propuestos para una fila todavía sin cargar.

    Mismas claves que los valores enviados por el formulario, para que la
    plantilla no tenga que distinguir entre una propuesta del sistema y algo
    que escribió el operador. `origen` solo sirve para explicarlo en pantalla.
    """
    if licencias:
        licencia = licencias[0]
        marca = _marca_de_licencia(licencia, marcas)

        if marca is not None:
            return {
                "marca": str(marca.pk),
                "horas": str(horas) if marca.requiere_horas else "",
                "licencia": str(licencia.pk),
                "obs": "",
                "origen": "licencia",
            }

    presente = marcas.get(CODIGO_PRESENTE)

    if presente is None:
        return {}

    return {
        "marca": str(presente.pk),
        "horas": "",
        "licencia": "",
        "obs": "",
        "origen": "presente",
    }


def _armar_filas(fecha, texto, valores, errores, *, solo_con_clase, marcas):
    """Una fila por designación vigente, con lo ya cargado y lo propuesto."""
    designaciones = list(
        _designaciones_del_dia(fecha, texto, solo_con_clase=solo_con_clase)
    )
    ids = [designacion.pk for designacion in designaciones]

    existentes = {
        registro.designacion_id: registro
        for registro in RegistroAsistencia.objects.select_related(
            "marca", "licencia__articulo"
        ).filter(fecha=fecha, designacion_id__in=ids)
    }
    licencias = _licencias_vigentes(ids, fecha)

    filas = []
    docente_anterior = None

    for designacion in designaciones:
        registro = existentes.get(designacion.pk)
        del_docente = licencias.get(designacion.pk, [])
        horas = horas_del_dia(designacion, fecha)
        enviados = valores.get(designacion.pk)

        if registro is not None:
            propuesta = {}
        elif enviados:
            propuesta = enviados
        else:
            propuesta = _sugerir(del_docente, marcas, horas)

        filas.append(
            {
                "designacion": designacion,
                "registro": registro,
                "licencias": del_docente,
                "valores": propuesta,
                "error": errores.get(designacion.pk),
                "horas_dia": horas,
                "horario": horario_del_dia(designacion, fecha),
                "dias_con_clase": dias_con_clase(designacion),
                "primera_del_docente": (
                    designacion.persona_id != docente_anterior
                ),
            }
        )
        docente_anterior = designacion.persona_id

    return filas


# Campos de la planilla por agente: agente-marca-<dni>, agente-horas-<dni>
# y agente-obs-<dni>.
CAMPO_MARCA_AGENTE = "agente-marca-"
CAMPO_HORAS_AGENTE = "agente-horas-"
CAMPO_OBS_AGENTE = "agente-obs-"
# Apartado de inasistencia: ¿se recibió el formulario? (si / no) y su número.
CAMPO_FORMULARIO_AGENTE = "agente-form-"
CAMPO_NRO_FORMULARIO_AGENTE = "agente-nroform-"


def _agrupar_por_agente(filas, valores_agente, errores_agente):
    """
    RF-07: una fila por docente. Recibe las filas por designación (ya
    ordenadas por docente) y las agrupa; cada agente lleva sus materias del
    día como detalle informativo.
    """
    agentes = []
    por_dni = {}

    for fila in filas:
        persona = fila["designacion"].persona
        agente = por_dni.get(persona.pk)

        if agente is None:
            agente = por_dni[persona.pk] = {
                "persona": persona,
                "materias": [],
            }
            agentes.append(agente)

        agente["materias"].append(fila)

    for agente in agentes:
        materias = agente["materias"]
        pendientes = [fila for fila in materias if fila["registro"] is None]
        dni = agente["persona"].pk

        agente["cargado"] = not pendientes
        agente["parcial"] = bool(pendientes) and len(pendientes) < len(materias)
        agente["horas_dia"] = sum(fila["horas_dia"] for fila in materias)
        agente["tiene_licencia"] = any(fila["licencias"] for fila in pendientes)

        enviados = valores_agente.get(dni)

        if enviados:
            agente["valores"] = enviados
        elif pendientes:
            propuesta = pendientes[0]["valores"] or {}
            agente["valores"] = {
                "marca": propuesta.get("marca", ""),
                # Las horas no se piden: salen del horario de cada materia.
                "horas": "",
                "obs": propuesta.get("obs", ""),
                "origen": propuesta.get("origen", ""),
            }
        else:
            agente["valores"] = {}

        agente["error"] = errores_agente.get(dni) or next(
            (fila["error"] for fila in materias if fila["error"]), None
        )

    return agentes


def _nombre_de(designacion):
    if designacion.espacio_curricular_id:
        return designacion.espacio_curricular.nombre
    return designacion.cargo.descripcion


def _sin_horario_cargado(fecha, texto, agentes):
    """
    RF-12: designaciones vigentes del día que no tienen NINGÚN horario
    cargado. Con «Solo los que dan clase» no aparecen en la lista y, si el
    docente da otra materia ese día, la marca no las alcanza. No se inventan
    horas: se avisa para que se cargue el horario en Personal.

    Devuelve ({dni: ["«Bedel»", …]} de los docentes que están en la lista,
    [personas] que no aparecen en la lista por no tener ningún horario).
    """
    en_lista = {agente["persona"].pk for agente in agentes}
    mostradas = {
        fila["designacion"].pk
        for agente in agentes
        for fila in agente["materias"]
    }
    por_agente = {}
    fuera = {}

    for designacion in _designaciones_del_dia(fecha, texto):
        if designacion.pk in mostradas or dias_con_clase(designacion):
            continue

        dni = designacion.persona_id

        if dni in en_lista:
            por_agente.setdefault(dni, []).append(f"«{_nombre_de(designacion)}»")
        else:
            fuera.setdefault(dni, designacion.persona)

    return por_agente, list(fuera.values())


def _leer_agentes(post, fecha, marcas_por_pk, *, solo_con_clase, ya_leidas):
    """
    RF-07: interpreta la planilla por agente. Por cada docente con una marca
    elegida arma una fila por cada designación suya del día que todavía no
    tiene registro, con las horas de su horario.

    Devuelve (filas, valores por dni, errores por dni, dni de cada
    designación). `ya_leidas` son las designaciones que llegaron en el
    formato por designación y no hay que repetir.
    """
    filas = []
    valores = {}
    errores = {}
    dni_de = {}

    for clave in post:
        if not clave.startswith(CAMPO_MARCA_AGENTE) or not post[clave]:
            continue

        dni = clave[len(CAMPO_MARCA_AGENTE):]

        if not dni.isdigit() or len(dni) > 10 or dni in valores:
            continue

        horas_texto = post.get(f"{CAMPO_HORAS_AGENTE}{dni}", "").strip()
        observaciones = post.get(f"{CAMPO_OBS_AGENTE}{dni}", "").strip()
        formulario = post.get(f"{CAMPO_FORMULARIO_AGENTE}{dni}", "")
        nro_formulario = post.get(f"{CAMPO_NRO_FORMULARIO_AGENTE}{dni}", "").strip()[:30]
        valores[dni] = {
            "marca": post[clave],
            "horas": horas_texto,
            "obs": observaciones,
            "formulario": formulario,
            "nro_formulario": nro_formulario,
        }

        marca = marcas_por_pk.get(_id_pedido(post[clave]))

        if marca is None:
            errores[dni] = "La marca elegida no es válida."
            continue

        try:
            horas_escritas = (
                Decimal(horas_texto.replace(",", "."))
                if horas_texto
                else None
            )
        except InvalidOperation:
            horas_escritas = Decimal("-1")

        if horas_escritas is not None and (
            not horas_escritas.is_finite() or horas_escritas < 0
        ):
            errores[dni] = "Las horas deben ser un número mayor o igual a cero."
            continue

        del_agente = _designaciones_del_dia(fecha).filter(persona_id=dni)
        designaciones = list(del_agente)

        if solo_con_clase:
            con_clase = [
                d for d in designaciones if horas_del_dia(d, fecha) > 0
            ]
            # Si ese día no tiene ninguna materia con horario cargado, la
            # novedad se asienta en todas sus designaciones vigentes.
            designaciones = con_clase or designaciones

        if not designaciones:
            errores[dni] = "El docente no tiene designaciones vigentes en esta fecha."
            continue

        cargadas = set(
            RegistroAsistencia.objects.filter(
                fecha=fecha, designacion__in=designaciones
            ).values_list("designacion_id", flat=True)
        )
        licencias = _licencias_vigentes(
            [d.pk for d in designaciones], fecha
        )

        for designacion in designaciones:
            if designacion.pk in cargadas or designacion.pk in ya_leidas:
                continue

            horas = horas_del_dia(designacion, fecha)

            if marca.requiere_horas and horas <= 0:
                # Sin horario cargado para hoy: valen las horas escritas.
                horas = horas_escritas or Decimal("0")

                if horas <= 0:
                    materia = (
                        designacion.espacio_curricular.nombre
                        if designacion.espacio_curricular
                        else designacion.cargo.descripcion
                    )
                    errores[dni] = (
                        f"«{materia}» no tiene horario cargado para este día: "
                        "escribí las horas sin cubrir."
                    )
                    break
            elif marca.requiere_horas and horas_escritas:
                # Un solo cargo ese día: se respeta lo que escribió el operador.
                if len(designaciones) == 1:
                    horas = horas_escritas

            licencia = None

            if marca.codigo in (CODIGO_LICENCIA, CODIGO_LARGO_TRATAMIENTO):
                del_cargo = licencias.get(designacion.pk, [])
                licencia = del_cargo[0] if del_cargo else None

            dni_de[designacion.pk] = dni
            filas.append(
                {
                    "designacion": designacion,
                    "marca": marca,
                    "horas_inasistidas": horas,
                    "licencia": licencia,
                    "observaciones": observaciones,
                    # Falta con el papel ya recibido: nace justificada.
                    "formulario_recibido": formulario == "si",
                    "nro_formulario": nro_formulario,
                }
            )

    if errores:
        filas = [
            fila for fila in filas
            if dni_de[fila["designacion"].pk] not in errores
        ]

    return filas, valores, errores, dni_de


def _valores_del_dia_anterior(fecha, texto, marcas_por_pk):
    """
    Lo cargado el día hábil anterior, como valores iniciales de la planilla.

    Sirve para repetir una jornada parecida sin tocar fila por fila. Devuelve
    (valores, fecha_copiada); fecha_copiada es None si no había nada que traer.
    """
    anterior = fecha

    # Hasta 10 días atrás: alcanza para saltar un fin de semana largo.
    for _ in range(10):
        candidata = _dia_vecino(anterior, -1)

        if candidata == anterior:
            return {}, None  # se llegó al límite del rango admitido

        anterior = candidata

        if motivo_dia_no_laborable(anterior) is None:
            break
    else:
        return {}, None

    designaciones = {
        designacion.pk
        for designacion in _designaciones_del_dia(fecha, texto)
    }
    registros = RegistroAsistencia.objects.select_related("marca").filter(
        fecha=anterior,
        designacion_id__in=designaciones,
    )

    valores = {}

    for registro in registros:
        if registro.marca_id not in marcas_por_pk:
            continue  # marca dada de baja del catálogo

        valores[registro.designacion_id] = {
            "marca": str(registro.marca_id),
            "horas": (
                str(registro.horas_inasistidas)
                if registro.marca.requiere_horas
                else ""
            ),
            "licencia": (
                str(registro.licencia_id) if registro.licencia_id else ""
            ),
            "obs": registro.observaciones,
            "origen": "copia",
        }

    return valores, (anterior if valores else None)


def _leer_planilla(post, fecha, marcas_por_pk):
    """
    Interpreta lo enviado por la planilla. Devuelve las filas listas para
    guardar, los valores enviados (para volver a mostrarlos) y los errores
    por designación.
    """
    prefijo = "marca-"
    ids = []

    for clave in post:
        if not clave.startswith(prefijo) or not post[clave]:
            continue

        # Un id que no entra en la clave de la base no identifica a ninguna
        # designación: descartarlo acá evita un error de rango en la consulta.
        numero = _id_pedido(clave[len(prefijo):])

        if numero is not None and numero not in ids:
            ids.append(numero)

    ids.sort()

    designaciones = {
        designacion.pk: designacion
        for designacion in _designaciones_del_dia(fecha).filter(pk__in=ids)
    }

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

        marca = marcas_por_pk.get(_id_pedido(marca_texto))

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

        if marca.requiere_horas and horas > Decimal("0"):
            horas_dia = horas_del_dia(designacion, fecha)
            if horas_dia > Decimal("0") and horas > horas_dia:
                errores[pk] = (
                    f"Las horas ({horas}) superan las "
                    f"{horas_dia} hs cátedra asignadas este día."
                )
                continue

        licencia = None

        if licencia_texto:
            licencia_id = _id_pedido(licencia_texto)
            licencia = (
                LicenciaOtorgada.objects.filter(
                    pk=licencia_id, designacion=designacion
                ).first()
                if licencia_id is not None
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


def _aviso_de_errores(filas, errores):
    """
    Mensaje de la planilla cuando algo no cierra (punto 3).

    El guardado es todo o nada, pero el operador necesita saber cuántas filas
    están bien y cuántas tiene que mirar: «no se guardó ninguna» a secas, con
    cuarenta docentes cargados, no le dice dónde buscar.
    """
    con_problema = len(errores)
    bien = max(len(filas) - con_problema, 0)

    if con_problema == 1:
        detalle = "1 fila tiene un problema"
    else:
        detalle = f"{con_problema} filas tienen un problema"

    if bien == 1:
        correctas = "1 fila está bien"
    else:
        correctas = f"{bien} filas están bien"

    return (
        f"{correctas} y {detalle}. No se guardó ninguna fila todavía: "
        "corregí lo que está marcado en rojo y volvé a tocar "
        "«Guardar planilla». Lo que cargaste no se perdió."
    )


def _motivo_de_bloqueo(request, fecha, cierre, jornada_cerrada, no_laborable):
    """Por qué no se puede cargar esta fecha, o None si se puede."""
    if fecha > timezone.localdate():
        return "No se puede registrar asistencia de una fecha futura."

    if no_laborable:
        return f"{no_laborable}: no corresponde registrar asistencia."

    if cierre and cierre.estado == CierreMensual.Estado.CERRADO:
        return "El período está cerrado. Solicitá una reapertura autorizada."

    if jornada_cerrada and not request.user.has_perm(
        "asistencias.modificar_jornada_cerrada"
    ):
        return (
            "La jornada está cerrada: modificarla requiere el permiso para "
            "modificar jornadas cerradas."
        )

    return None


@vista_protegida("asistencias.add_registroasistencia", methods=["GET", "POST"])
def planilla_rapida(request):
    """Planilla de marcado del día: una fila por agente (RF-07)."""
    origen = request.POST if request.method == "POST" else request.GET
    hoy = timezone.localdate()
    fecha = _fecha_pedida(origen.get("fecha"), por_defecto=hoy)

    if fecha is None:
        messages.error(request, "La fecha seleccionada no es válida.")
        return redirect("asistencia:planilla_rapida")

    texto = origen.get("q", "").strip()
    alcance = (
        ALCANCE_TODOS
        if origen.get("alcance") == ALCANCE_TODOS
        else ALCANCE_CON_CLASE
    )

    marcas = list(MarcaAsistencia.vigentes())
    marcas_por_codigo = {marca.codigo: marca for marca in marcas}
    marcas_por_pk = {marca.pk: marca for marca in marcas}

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
    bloqueo = _motivo_de_bloqueo(
        request, fecha, cierre, jornada_cerrada, motivo_no_laborable
    )

    valores = {}
    errores = {}
    valores_agente = {}
    errores_agente = {}
    copiado_de = None

    if request.method == "POST" and request.POST.get("accion") == "copiar":
        if bloqueo:
            messages.error(request, bloqueo)
        else:
            valores, copiado_de = _valores_del_dia_anterior(
                fecha, texto, marcas_por_pk
            )

            if copiado_de is None:
                messages.info(
                    request,
                    "No hay nada cargado en el día hábil anterior para copiar.",
                )
            else:
                messages.info(
                    request,
                    f"Se trajo lo cargado el {copiado_de:%d/%m/%Y}. "
                    "Revisalo y guardá la planilla.",
                )
    elif request.method == "POST":
        if bloqueo:
            messages.error(request, bloqueo)
        else:
            filas, valores, errores = _leer_planilla(
                request.POST, fecha, marcas_por_pk
            )
            # RF-07: una marca por agente, que se reparte entre sus materias.
            (
                filas_agente,
                valores_agente,
                errores_agente,
                dni_de,
            ) = _leer_agentes(
                request.POST,
                fecha,
                marcas_por_pk,
                solo_con_clase=(alcance == ALCANCE_CON_CLASE),
                ya_leidas={fila["designacion"].pk for fila in filas},
            )
            filas = filas + filas_agente

            if errores or errores_agente:
                messages.error(
                    request,
                    _aviso_de_errores(filas, {**errores, **errores_agente}),
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
                    for pk, mensaje in exc.errores.items():
                        if pk in dni_de:
                            errores_agente.setdefault(dni_de[pk], mensaje)
                    messages.error(
                        request, _aviso_de_errores(filas, errores)
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

    filas = _armar_filas(
        fecha,
        texto,
        valores,
        errores,
        solo_con_clase=(alcance == ALCANCE_CON_CLASE),
        marcas=marcas_por_codigo,
    )

    # Si ninguna designación tiene horario cargado para este día, filtrar por
    # horario dejaría la planilla vacía: se muestran todas y se avisa, para
    # que el sistema siga siendo usable mientras se cargan los horarios.
    sin_horarios = False

    if not filas and alcance == ALCANCE_CON_CLASE:
        todas = _armar_filas(
            fecha,
            texto,
            valores,
            errores,
            solo_con_clase=False,
            marcas=marcas_por_codigo,
        )

        if todas:
            filas = todas
            sin_horarios = True
            alcance = ALCANCE_TODOS

    ciclo = ciclo_lectivo_actual()

    # Lo traído del día anterior llega por designación: para la fila del
    # agente vale lo de su primera materia.
    for fila in filas:
        dni = fila["designacion"].persona_id
        copiado = valores.get(fila["designacion"].pk)

        if copiado and copiado.get("origen") == "copia":
            valores_agente.setdefault(
                dni, {**copiado, "horas": ""}
            )

    agentes = _agrupar_por_agente(filas, valores_agente, errores_agente)

    # RF-12: aviso de las designaciones sin ningún horario cargado, que con
    # «Solo los que dan clase» no reciben la marca (con «Todos» sí aparecen).
    sin_horario_por_agente, fuera_sin_horario = (
        _sin_horario_cargado(fecha, texto, agentes)
        if alcance == ALCANCE_CON_CLASE
        else ({}, [])
    )
    for agente in agentes:
        agente["sin_horario"] = sin_horario_por_agente.get(agente["persona"].pk, [])

    # RF-18: aviso visual a quien carga, antes de que se agote el límite
    # anual de inasistencias y permisos. Import local: reportes importa
    # asistencias, no al revés.
    from reportes.selectors import estados_de_inasistencias

    en_alerta = estados_de_inasistencias(
        fecha.year, {agente["persona"].pk for agente in agentes}
    )
    for agente in agentes:
        agente["alerta"] = en_alerta.get(agente["persona"].pk)
    marcadas = sum(1 for agente in agentes if agente["cargado"])

    # Pendientes (faltas sin resolver y licencias sin completar): aviso al día
    # hábil siguiente, obligatorio al segundo. Se calculan respecto de hoy.
    from ..services import ESTADO_VENCIDO, avisos_del_dia

    lista_pendientes = avisos_del_dia(hoy)

    # Fechas del aviso «LIC pendiente»: aviso al día hábil siguiente y
    # vencimiento al segundo, contados desde el día que se está cargando.
    from ..services.pendientes import plazos

    plazo_aviso, plazo_vence = plazos(fecha)

    # Punto 6: si el día no es hábil o es futuro, ofrecer el día en el que sí
    # corresponde cargar, para que el aviso tenga una salida.
    dia_habil_sugerido = (
        dia_habil_mas_cercano(fecha, sentido=-1)
        if (motivo_no_laborable or fecha > hoy)
        else None
    )

    return render(
        request,
        "asistencias/planilla_rapida.html",
        {
            "fecha": fecha,
            "fecha_texto": fecha.isoformat(),
            "texto": texto,
            "alcance": alcance,
            "alcance_todos": ALCANCE_TODOS,
            "alcance_con_clase": ALCANCE_CON_CLASE,
            "sin_horarios": sin_horarios,
            "fuera_sin_horario": fuera_sin_horario,
            "ciclo_lectivo": ciclo,
            "fuera_del_ciclo": fecha.year != ciclo,
            "filas": filas,
            "agentes": agentes,
            "marcas": marcas,
            "marca_presente": marcas_por_codigo.get(CODIGO_PRESENTE),
            "bloqueo": bloqueo,
            "aviso_calendario": aviso_del_calendario(fecha),
            "jornada_cerrada": jornada_cerrada,
            "copiado_de": copiado_de,
            "total": len(agentes),
            "marcadas": marcadas,
            "pendientes": len(agentes) - marcadas,
            "cantidad_errores": len(
                {agente["persona"].pk for agente in agentes if agente["error"]}
            ),
            "dia_habil_sugerido": dia_habil_sugerido,
            "es_hoy": fecha == hoy,
            "lista_pendientes": lista_pendientes,
            "hay_vencidos": any(
                p["estado"] == ESTADO_VENCIDO for p in lista_pendientes
            ),
            "volver": request.get_full_path(),
            "codigo_inasistencia": "I",
            "plazo_aviso": plazo_aviso,
            "plazo_vence": plazo_vence,
            **contexto_sesion(request),
        },
    )
