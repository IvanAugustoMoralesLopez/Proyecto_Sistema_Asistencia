"""
Planilla rápida: carga de todas las marcas del día en una sola pantalla
(RF-07).

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
from personal.models import Designacion

from ..models import (
    CierreDiario,
    CierreMensual,
    MarcaAsistencia,
    RegistroAsistencia,
    licencia_cubre_fecha,
)
from ..services import (
    PlanillaConErrores,
    ciclo_lectivo_actual,
    clave_dia,
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
    vista_protegida,
)

# Valores del selector «a quiénes mostrar».
ALCANCE_CON_CLASE = "clase"
ALCANCE_TODOS = "todos"

# Marcas que se proponen automáticamente.
CODIGO_PRESENTE = "P"
CODIGO_LICENCIA = "LIC"
CODIGO_LARGO_TRATAMIENTO = "LT"
TEXTO_LARGO_TRATAMIENTO = "largo tratamiento"


def _designaciones_del_dia(fecha, texto="", solo_con_clase=False):
    """Designaciones vigentes en la fecha, ordenadas por docente."""
    designaciones = (
        Designacion.objects.filter(
            activo=True,
            persona__activa=True,
            desde__lte=fecha,
        )
        .filter(Q(hasta__isnull=True) | Q(hasta__gte=fecha))
        .select_related("persona", "cargo", "espacio_curricular")
        .prefetch_related("horarios")
        .order_by("persona__apellido_nombre", "persona_id", "id")
    )

    if texto:
        designaciones = designaciones.filter(
            Q(persona__apellido_nombre__icontains=texto)
            | Q(persona__dni__icontains=texto)
        )

    dia = clave_dia(fecha)

    if solo_con_clase and dia:
        # distinct(): una designación con varios horarios ese día se repetiría.
        designaciones = designaciones.filter(horarios__dia=dia).distinct()

    return designaciones


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
            "marca", "licencia"
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
            "La jornada está cerrada: modificarla requiere autorización "
            "de Secretaría o Subsecretaría."
        )

    return None


@vista_protegida("asistencias.add_registroasistencia", methods=["GET", "POST"])
def planilla_rapida(request):
    """Planilla de marcado del día: una fila por designación vigente."""
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
    marcadas = sum(1 for fila in filas if fila["registro"])

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
            "ciclo_lectivo": ciclo,
            "fuera_del_ciclo": fecha.year != ciclo,
            "filas": filas,
            "marcas": marcas,
            "marca_presente": marcas_por_codigo.get(CODIGO_PRESENTE),
            "bloqueo": bloqueo,
            "jornada_cerrada": jornada_cerrada,
            "copiado_de": copiado_de,
            "total": len(filas),
            "marcadas": marcadas,
            "pendientes": len(filas) - marcadas,
        },
    )
