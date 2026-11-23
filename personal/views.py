import csv
import io
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError, RestrictedError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.http import HttpResponse, JsonResponse

from reportes.auditoria import AccionesReportes, registrar_evento

from .forms import (
    BuscarLegajoForm,
    CarreraForm,
    CargoForm,
    DesignacionForm,
    EspacioCurricularForm,
    NuevaDesignacionForm,
    PersonaForm,
    TipoInstrumentoLegalForm,
    interpretar_fecha_de_vigencia,
)
from .models import (
    FECHA_SIN_INICIO,
    TEXTO_SIN_INICIO,
    TEXTO_SIN_TERMINO,
    Cargo,
    Carrera,
    Designacion,
    Especialidad,
    EspacioCurricular,
    Horario,
    ImportacionPersonalError,
    Persona,
    TipoInstrumentoLegal,
    UnidadEducativa,
)
from licencias.models import LicenciaArticulo, LicenciaOtorgada
from licencias.forms import LicenciaArticuloForm

MAX_FILAS_VISTA_PREVIA = 100
COLUMNAS_CSV_PERSONAL = (
    "dni",
    "nombre_apellido",
    "sexo",
    "fecha_nacimiento",
    "estado_civil",
    "nacionalidad",
    "nro_dgi",
    "nro_dgr",
    "telefono",
    "email",
    "domicilio_calle",
    "barrio",
    "localidad",
    "codigo_postal",
    "provincia",
    "activa",
    "cargo_codigo",
    "espacio_curricular",
    "carrera",
    "unidad_educativa_id",
    "especialidad",
    "situacion_revista",
    "anio_curso",
    "division_seccion",
    "turno",
    "hs_catedra",
    "desde",
    "hasta",
    "horas_lun",
    "horas_mar",
    "horas_mie",
    "horas_jue",
    "horas_vie",
    "observaciones",
    "disp_alta_nro",
    "sello_regional_as",
    "norma_tipo",
    "norma_numero",
    "norma_anio",
    "organismo_emisor",
    "pof",
    "anio_pof",
    "novedad",
    "es_suplencia",
    "plazo_indeterminado",
    "reemplaza_id",
)

# Clave de sesión donde queda el CSV ya validado a la espera de la
# confirmación de la persona administradora (RF-06).
SESION_CSV = "personal_csv_pendiente"

# Columnas del CSV con las horas cátedra de cada día (RF-03 / RF-06).
COLUMNAS_HORAS = {
    "horas_lun": Horario.Dia.LUNES,
    "horas_mar": Horario.Dia.MARTES,
    "horas_mie": Horario.Dia.MIERCOLES,
    "horas_jue": Horario.Dia.JUEVES,
    "horas_vie": Horario.Dia.VIERNES,
}
COLUMNAS_DESIGNACION = {
    "espacio_curricular",
    "carrera",
    "unidad_educativa_id",
    "especialidad",
    "situacion_revista",
    "anio_curso",
    "division_seccion",
    "turno",
    "hs_catedra",
    "desde",
    "hasta",
    "observaciones",
    "disp_alta_nro",
    "sello_regional_as",
    "norma_tipo",
    "norma_numero",
    "norma_anio",
    "organismo_emisor",
    "pof",
    "anio_pof",
    "novedad",
    "es_suplencia",
    "plazo_indeterminado",
    "reemplaza_id",
    *COLUMNAS_HORAS,
}
ALIAS_COLUMNAS_CSV = {
    "nombre_y_apellido",
    "apellido_nombre",
    "apellido",
    "nombres",
}


def _entero_csv(fila, columna, *, maximo=None):
    valor = (fila.get(columna) or "").strip()
    if not valor:
        return None
    if not valor.isdigit() or (maximo is not None and int(valor) > maximo):
        raise ValidationError(
            f"La columna '{columna}' debe ser un número entero válido."
        )
    return int(valor)


def _booleano_csv(valor, columna):
    valor = (valor or "").strip().lower()
    if valor in {"1", "si", "sí", "true", "verdadero"}:
        return True
    if valor in {"0", "no", "false", "falso"}:
        return False
    raise ValidationError(
        f"La columna '{columna}' debe indicar sí/no o true/false."
    )


def _fecha_de_vigencia_csv(texto, columna, especial):
    """RN-09: fecha (AAAA-MM-DD o dd/mm/aaaa) o la cadena especial de la columna."""
    try:
        valor = interpretar_fecha_de_vigencia(texto)
    except ValueError as exc:
        raise ValidationError(
            f"La fecha '{columna}' debe tener formato AAAA-MM-DD "
            f"(o dd/mm/aaaa) o ser {especial}."
        ) from exc

    if isinstance(valor, str) and valor != especial:
        raise ValidationError(
            f"En la columna '{columna}' la cadena especial es {especial}."
        )

    return valor


def _horas_de_la_fila(fila):
    """Horas por día indicadas en la fila: {dia: horas}. Vacío = no indicado."""
    horas = {}

    for columna, dia in COLUMNAS_HORAS.items():
        texto = (fila.get(columna) or "").strip()

        if not texto:
            continue

        if not texto.isdigit() or int(texto) > 255:
            raise ValidationError(
                f"La columna '{columna}' debe ser un número entero de horas."
            )

        if int(texto):
            horas[dia] = int(texto)

    return horas


def _pk_valido(modelo, valor):
    if not valor:
        return None
    if modelo._meta.pk.get_internal_type() == "CharField":
        return valor
    return valor if str(valor).isdigit() else None


def _mensaje_errores(exc):
    if isinstance(exc, ValidationError):
        if hasattr(exc, "message_dict"):
            return "; ".join(
                f"{campo}: {', '.join(errores)}"
                for campo, errores in exc.message_dict.items()
            )
        return "; ".join(exc.messages)
    return str(exc)


def _puede_consultar_legajos(usuario):
    permisos = (
        "personal.view_persona",
        "personal.add_persona",
        "personal.change_persona",
        "personal.view_designacion",
        "personal.add_designacion",
        "personal.change_designacion",
    )
    return any(usuario.has_perm(permiso) for permiso in permisos)


def _puede_importar_csv(usuario):
    permisos = (
        "personal.add_persona",
        "personal.change_persona",
        "personal.add_designacion",
    )
    return any(usuario.has_perm(permiso) for permiso in permisos)


def _importar_fila_personal(fila, usuario=None):
    dni = (fila.get("dni") or "").strip()
    if not dni:
        raise ValidationError("Falta el DNI.")

    persona = Persona.objects.filter(pk=dni).first()
    apellido_nombre = (
        fila.get("nombre_apellido")
        or fila.get("nombre_y_apellido")
        or fila.get("apellido_nombre")
        or ""
    ).strip()
    apellido = (fila.get("apellido") or "").strip()
    nombres = (fila.get("nombres") or "").strip()
    if not apellido_nombre and not (apellido or nombres):
        if persona is None:
            raise ValidationError(
                "El DNI no existe y la fila no contiene datos personales para crearlo."
            )
    else:
        permiso_persona = (
            "personal.change_persona"
            if persona is not None
            else "personal.add_persona"
        )
        if usuario and not usuario.has_perm(permiso_persona):
            raise ValidationError(
                f"No tiene permiso para registrar el legajo con DNI {dni}."
            )
        persona = persona or Persona(dni=dni)
        apellido_actual = (fila.get("apellido") or "").strip() or persona.apellido
        nombres_actuales = (fila.get("nombres") or "").strip() or persona.nombres
        if apellido_nombre:
            persona.apellido_nombre = apellido_nombre
            if "," in apellido_nombre:
                apellido_actual, nombres_actuales = (
                    parte.strip() for parte in apellido_nombre.split(",", 1)
                )
            else:
                apellido_actual, nombres_actuales = apellido_nombre, ""
            persona.apellido = apellido_actual
            persona.nombres = nombres_actuales
        elif "apellido" in fila or "nombres" in fila:
            persona.apellido_nombre = ", ".join(
                parte for parte in (apellido_actual, nombres_actuales) if parte
            )
            persona.apellido = apellido_actual
            persona.nombres = nombres_actuales
        for campo in (
            "sexo",
            "estado_civil",
            "nacionalidad",
            "nro_dgi",
            "nro_dgr",
            "telefono",
            "email",
            "localidad",
            "domicilio_calle",
            "barrio",
            "codigo_postal",
            "provincia",
        ):
            if campo in fila:
                setattr(persona, campo, (fila.get(campo) or "").strip())
        fecha_nacimiento = (fila.get("fecha_nacimiento") or "").strip()
        if fecha_nacimiento:
            try:
                persona.fecha_nacimiento = date.fromisoformat(fecha_nacimiento)
            except ValueError as exc:
                raise ValidationError(
                    "La columna 'fecha_nacimiento' debe tener formato AAAA-MM-DD."
                ) from exc
        elif "fecha_nacimiento" in fila:
            persona.fecha_nacimiento = None
        if (fila.get("activa") or "").strip():
            persona.activa = _booleano_csv(fila["activa"], "activa")
        persona.full_clean()
        persona.save()

    codigo_cargo = (fila.get("cargo_codigo") or "").strip()
    if not codigo_cargo:
        columnas_designacion_con_valor = [
            columna
            for columna in COLUMNAS_DESIGNACION
            if (fila.get(columna) or "").strip()
        ]
        if columnas_designacion_con_valor:
            raise ValidationError(
                "La fila contiene datos de designación pero no tiene 'cargo_codigo'."
            )
        return {
            "dni": persona.dni,
            "nombre": persona.apellido_nombre,
            "cargo": "",
            "espacio": "",
            "resultado": "Solo legajo",
        }

    if usuario and not usuario.has_perm("personal.add_designacion"):
        raise ValidationError(
            f"No tiene permiso para registrar la designación del DNI {dni}."
        )

    cargo = Cargo.objects.filter(pk=codigo_cargo).first()
    if cargo is None:
        raise ValidationError(f"No existe el cargo '{codigo_cargo}'.")

    espacio_nombre = (fila.get("espacio_curricular") or "").strip()
    carrera_nombre = (fila.get("carrera") or "").strip()
    espacio = None
    if espacio_nombre:
        espacios = EspacioCurricular.objects.filter(
            nombre__iexact=espacio_nombre,
            activo=True,
        )
        if carrera_nombre:
            espacios = espacios.filter(carrera__nombre__iexact=carrera_nombre)
        elif espacios.count() > 1:
            raise ValidationError(
                f"El espacio curricular '{espacio_nombre}' existe en más de "
                "una carrera: indique la columna 'carrera'."
            )
        espacio = espacios.first()
        if espacio is None:
            raise ValidationError(
                f"No existe el espacio curricular '{espacio_nombre}'"
                + (f" en la carrera '{carrera_nombre}'." if carrera_nombre else ".")
            )

    unidad_educativa = None
    unidad_educativa_id = (fila.get("unidad_educativa_id") or "").strip()
    if unidad_educativa_id:
        if not unidad_educativa_id.isdigit():
            raise ValidationError(
                "La columna 'unidad_educativa_id' debe ser un identificador numérico."
            )
        unidad_educativa = UnidadEducativa.objects.filter(
            pk=unidad_educativa_id, activa=True
        ).first()
        if unidad_educativa is None:
            raise ValidationError(
                f"No existe la unidad educativa '{unidad_educativa_id}'."
            )

    especialidad = None
    especialidad_nombre = (fila.get("especialidad") or "").strip()
    if especialidad_nombre:
        especialidad = Especialidad.objects.filter(
            titulo__iexact=especialidad_nombre, activa=True
        ).first()
        if especialidad is None:
            raise ValidationError(
                f"No existe la especialidad '{especialidad_nombre}'."
            )

    # RN-09: 'desde' admite una fecha o SIN INICIO.
    desde = _fecha_de_vigencia_csv(
        fila.get("desde"), "desde", TEXTO_SIN_INICIO
    )
    if desde is None:
        raise ValidationError(
            "Falta la fecha 'desde' (AAAA-MM-DD, dd/mm/aaaa o SIN INICIO)."
        )
    sin_inicio = desde == TEXTO_SIN_INICIO
    if sin_inicio:
        desde = FECHA_SIN_INICIO

    horas_por_dia = _horas_de_la_fila(fila)

    norma_tipo = (fila.get("norma_tipo") or "").strip()
    if norma_tipo:
        tipo = TipoInstrumentoLegal.objects.filter(
            nombre__iexact=norma_tipo
        ).first()
        if tipo is None:
            raise ValidationError(
                f"No existe el tipo de instrumento legal '{norma_tipo}'. "
                "Agréguelo en Catálogos → Instrumentos legales."
            )
        norma_tipo = tipo.nombre

    situacion = (fila.get("situacion_revista") or "").strip().upper()
    situacion = {
        "TITULAR": Designacion.Situacion.TITULAR,
        "INTERINO": Designacion.Situacion.INTERINO,
        "SUPLENTE": Designacion.Situacion.SUPLENTE,
    }.get(situacion, situacion)
    reemplaza = None
    reemplaza_id = (fila.get("reemplaza_id") or "").strip()
    if reemplaza_id:
        if not reemplaza_id.isdigit():
            raise ValidationError(
                "La columna 'reemplaza_id' debe contener un identificador numérico."
            )
        reemplaza = Designacion.objects.filter(pk=reemplaza_id).first()
        if reemplaza is None:
            raise ValidationError(
                f"No existe la designación reemplazada '{reemplaza_id}'."
            )
    designacion = Designacion(
        persona=persona,
        cargo=cargo,
        espacio_curricular=espacio,
        unidad_educativa=unidad_educativa,
        especialidad=especialidad,
        reemplaza=reemplaza,
        situacion_revista=situacion,
        norma_tipo=norma_tipo,
        norma_numero=(fila.get("norma_numero") or "").strip(),
        norma_anio=_entero_csv(fila, "norma_anio", maximo=2200),
        organismo_emisor=(fila.get("organismo_emisor") or "").strip(),
        observaciones=(fila.get("observaciones") or "").strip(),
        anio_curso=(fila.get("anio_curso") or "").strip(),
        division_seccion=(fila.get("division_seccion") or "").strip(),
        turno=(fila.get("turno") or "").strip(),
        hs_catedra=_entero_csv(fila, "hs_catedra", maximo=255),
        disp_alta_nro=(fila.get("disp_alta_nro") or "").strip(),
        sello_regional_as=(fila.get("sello_regional_as") or "").strip(),
        pof=(fila.get("pof") or "").strip(),
        anio_pof=_entero_csv(fila, "anio_pof", maximo=2200),
        novedad=(fila.get("novedad") or "").strip(),
        desde=desde,
        sin_inicio=sin_inicio,
        es_suplencia=(
            _booleano_csv(fila["es_suplencia"], "es_suplencia")
            if (fila.get("es_suplencia") or "").strip()
            else False
        ),
        plazo_indeterminado=(
            _booleano_csv(fila["plazo_indeterminado"], "plazo_indeterminado")
            if (fila.get("plazo_indeterminado") or "").strip()
            else False
        ),
    )
    # RN-09: 'hasta' admite una fecha o SIN TERMINO (o quedar vacío).
    hasta = _fecha_de_vigencia_csv(
        fila.get("hasta"), "hasta", TEXTO_SIN_TERMINO
    )
    if hasta == TEXTO_SIN_TERMINO:
        hasta = None
        if designacion.es_suplencia:
            designacion.plazo_indeterminado = True
    designacion.hasta = hasta

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

    # RF-03 / RF-06: distribución horaria por día de la designación.
    for dia, horas in horas_por_dia.items():
        Horario.objects.create(
            designacion=designacion, dia=dia, horas_catedra=horas
        )
    return {
        "dni": persona.dni,
        "nombre": persona.apellido_nombre,
        "cargo": cargo.descripcion,
        "espacio": espacio.nombre if espacio else "",
        "resultado": "Legajo y designación",
    }


class _DeshacerSimulacion(Exception):
    """Fuerza el rollback de la importación simulada."""


def _leer_archivo_csv(archivo):
    """Valida extensión y codificación. Devuelve (nombre, contenido)."""
    if not archivo.name.lower().endswith(".csv"):
        raise ValidationError("El archivo seleccionado debe tener extensión .csv.")

    try:
        contenido = archivo.read().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError("El archivo debe estar codificado en UTF-8.") from exc

    return archivo.name[:255], contenido


def _importar_contenido(
    nombre,
    contenido,
    usuario=None,
    *,
    simular=False,
    filas_previas=None,
):
    """
    Recorre el CSV fila por fila. Devuelve (total, rechazos), donde cada
    rechazo es {"fila", "dni", "motivo"}.

    Con `simular=True` hace exactamente las mismas validaciones (duplicados e
    inconsistencias) pero no deja nada guardado: es la vista previa que la
    persona administradora confirma antes de importar (RF-06).
    """
    try:
        dialecto = csv.Sniffer().sniff(
            contenido[:4096], delimiters=",;\t"
        )
    except csv.Error:
        dialecto = csv.excel
    lector = csv.DictReader(io.StringIO(contenido), dialect=dialecto)
    if not lector.fieldnames:
        raise ValidationError("El CSV debe incluir una fila de encabezados.")
    lector.fieldnames = [campo.strip().lower() for campo in lector.fieldnames]
    if "dni" not in lector.fieldnames:
        raise ValidationError("El CSV debe incluir una columna 'dni'.")
    if len(set(lector.fieldnames)) != len(lector.fieldnames):
        raise ValidationError("El CSV no puede repetir nombres de columnas.")
    columnas_admitidas = set(COLUMNAS_CSV_PERSONAL) | ALIAS_COLUMNAS_CSV
    columnas_desconocidas = set(lector.fieldnames) - columnas_admitidas
    if columnas_desconocidas:
        raise ValidationError(
            "Columnas no reconocidas: "
            + ", ".join(sorted(columnas_desconocidas))
            + ". Descargue la plantilla CSV para ver los nombres admitidos."
        )

    total = 0
    rechazos = []

    try:
        with transaction.atomic():
            for numero_fila, fila in enumerate(lector, start=2):
                total += 1
                try:
                    if None in fila or any(valor is None for valor in fila.values()):
                        raise ValidationError(
                            "La fila no tiene la misma cantidad de columnas que el encabezado."
                        )
                    with transaction.atomic():
                        detalle = _importar_fila_personal(
                            fila, usuario=usuario
                        )
                    if simular and filas_previas is not None:
                        if len(filas_previas) < MAX_FILAS_VISTA_PREVIA:
                            filas_previas.append(
                                {
                                    "fila": numero_fila,
                                    **detalle,
                                }
                            )
                except (ValidationError, IntegrityError, ValueError) as exc:
                    rechazos.append(
                        {
                            "fila": numero_fila,
                            "dni": (fila.get("dni") or "")[:20],
                            "motivo": _mensaje_errores(exc)[:255],
                            "original": fila,
                        }
                    )

            if simular:
                raise _DeshacerSimulacion
    except _DeshacerSimulacion:
        pass

    if not simular:
        for rechazo in rechazos:
            ImportacionPersonalError.objects.create(
                archivo=nombre,
                numero_fila=rechazo["fila"],
                dni_texto=rechazo["dni"],
                motivo_error=rechazo["motivo"],
                fila_original=rechazo["original"],
            )

    return total, rechazos


def _procesar_csv(archivo, usuario=None):
    """Importa el archivo de una vez. Devuelve (total, rechazadas)."""
    nombre, contenido = _leer_archivo_csv(archivo)
    total, rechazos = _importar_contenido(nombre, contenido, usuario)
    return total, len(rechazos)


@login_required
@require_http_methods(["GET", "POST"])
def gestion_legajos(request):
    if request.method == "GET" and not _puede_consultar_legajos(request.user):
        raise PermissionDenied

    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "importar_csv":
            # RF-06, paso 1: se valida todo el archivo SIN guardar nada y se
            # muestra el resultado para que la administradora lo confirme.
            if not _puede_importar_csv(request.user):
                raise PermissionDenied
            archivo = request.FILES.get("archivo")
            if not archivo:
                messages.error(request, "Seleccione un archivo CSV.")
                return redirect(reverse("personal:gestion_legajos"))
            try:
                nombre, contenido = _leer_archivo_csv(archivo)
                filas_previas = []
                total, rechazos = _importar_contenido(
                    nombre,
                    contenido,
                    usuario=request.user,
                    simular=True,
                    filas_previas=filas_previas,
                )
            except ValidationError as exc:
                messages.error(request, _mensaje_errores(exc))
                return redirect(reverse("personal:gestion_legajos"))

            request.session[SESION_CSV] = {
                "nombre": nombre,
                "contenido": contenido,
            }
            return render(
                request,
                "personal/gestion_legajos.html",
                {
                    **_contexto_pantalla(request),
                    "csv_pendiente": {
                        "nombre": nombre,
                        "total": total,
                        "validas": total - len(rechazos),
                        "filas": filas_previas,
                        "filas_mostradas": len(filas_previas),
                        "limite_filas": MAX_FILAS_VISTA_PREVIA,
                        "rechazos": [
                            {k: r[k] for k in ("fila", "dni", "motivo")}
                            for r in rechazos
                        ],
                    },
                },
            )

        if accion == "cancelar_csv":
            request.session.pop(SESION_CSV, None)
            messages.info(request, "La importación se canceló: no se guardó nada.")
            return redirect(reverse("personal:gestion_legajos"))

        if accion == "confirmar_csv":
            # RF-06, paso 2: la administradora confirmó; recién ahora se guarda.
            if not _puede_importar_csv(request.user):
                raise PermissionDenied
            pendiente = request.session.pop(SESION_CSV, None)
            if not pendiente:
                messages.error(
                    request,
                    "No hay ninguna importación pendiente de confirmar. "
                    "Vuelva a seleccionar el archivo.",
                )
                return redirect(reverse("personal:gestion_legajos"))
            try:
                total, rechazos = _importar_contenido(
                    pendiente["nombre"],
                    pendiente["contenido"],
                    usuario=request.user,
                )
            except ValidationError as exc:
                messages.error(request, _mensaje_errores(exc))
            else:
                rechazadas = len(rechazos)
                registrar_evento(
                    request.user,
                    AccionesReportes.IMPORTACION,
                    motivo=f"Archivo {pendiente['nombre']}"[:500],
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
            permiso = (
                "personal.change_persona"
                if persona_existente
                else "personal.add_persona"
            )
            if not request.user.has_perm(permiso):
                raise PermissionDenied
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
            dni = request.POST.get("dni", "").strip()
            persona = get_object_or_404(Persona, pk=dni)
            designacion_id = request.POST.get("designacion_id")
            designacion = None
            if designacion_id:
                if _pk_valido(Designacion, designacion_id) is None:
                    messages.error(request, "La designación indicada no existe.")
                    return redirect(
                        f"{reverse('personal:gestion_legajos')}?dni={persona.pk}"
                    )
                designacion = get_object_or_404(
                    Designacion,
                    pk=designacion_id,
                    persona=persona,
                )
            permiso = "personal.change_designacion"
            if accion == "guardar_designacion" and not designacion:
                permiso = "personal.add_designacion"
            if not request.user.has_perm(permiso):
                raise PermissionDenied

            if accion == "dar_baja_designacion":
                if designacion is None:
                    messages.error(request, "La designación indicada no existe.")
                    return redirect(
                        f"{reverse('personal:gestion_legajos')}?dni={persona.pk}"
                    )
                if designacion.activo:
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
            form.instance.persona = persona
            if form.is_valid():
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
        designacion_pk = _pk_valido(Designacion, designacion_id)
        if designacion_pk is not None:
            designacion = Designacion.objects.filter(
                pk=designacion_pk,
                persona=persona,
            ).first()
        else:
            messages.error(request, "La designación indicada no existe.")

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
    dni_filtro = None
    cargo = None
    espacio = None
    if filtro.is_valid():
        dni_filtro = filtro.cleaned_data.get("dni")
        cargo = filtro.cleaned_data.get("cargo")
        espacio = filtro.cleaned_data.get("espacio_curricular")
        if dni_filtro:
            resultados = resultados.filter(
                Q(persona__dni__icontains=dni_filtro)
                | Q(persona__apellido_nombre__icontains=dni_filtro)
            )
        if cargo:
            resultados = resultados.filter(cargo=cargo)
        if espacio:
            resultados = resultados.filter(espacio_curricular=espacio)

    agentes = Persona.objects.all().order_by("apellido_nombre", "dni")
    if filtro.is_valid():
        if dni_filtro:
            agentes = agentes.filter(
                Q(dni__icontains=dni_filtro)
                | Q(apellido_nombre__icontains=dni_filtro)
            )
        filtros_designacion = {}
        if cargo:
            filtros_designacion["designaciones__cargo"] = cargo
        if espacio:
            filtros_designacion["designaciones__espacio_curricular"] = espacio
        if filtros_designacion:
            filtros_designacion["designaciones__activo"] = True
            agentes = agentes.filter(**filtros_designacion).distinct()

    if persona:
        designaciones = persona.designaciones.select_related(
            "cargo",
            "espacio_curricular",
            "espacio_curricular__carrera",
        ).prefetch_related("horarios", "historial")
    else:
        designaciones = Designacion.objects.none()

    hoy = timezone.localdate()
    alertas_licencias = list(
        LicenciaOtorgada.objects.filter(
            hasta__gte=hoy,
            hasta__lte=hoy + timedelta(days=30),
        ).select_related("designacion__persona", "designacion__cargo")[:20]
    )

    return {
        "filtro": filtro,
        "persona_form": form,
        "designacion_form": designacion_form,
        "persona": persona,
        "designacion_seleccionada": designacion_seleccionada,
        "designaciones": designaciones,
        "resultados": resultados,
        "agentes": Paginator(agentes, 25).get_page(
            request.GET.get("pagina")
        ),
        "cargos": Cargo.objects.filter(activo=True).order_by("descripcion"),
        "espacios": EspacioCurricular.objects.filter(activo=True)
        .select_related("carrera")
        .order_by("carrera__nombre", "nombre"),
        "errores_importacion": ImportacionPersonalError.objects.all()[:10],
        "puede_guardar_persona": request.user.has_perm(
            "personal.change_persona" if persona else "personal.add_persona"
        ),
        "puede_guardar_designacion": request.user.has_perm(
            "personal.change_designacion"
            if designacion_seleccionada
            else "personal.add_designacion"
        ),
        "puede_importar_csv": _puede_importar_csv(request.user),
        "alertas_designaciones": Designacion.objects.filter(
            activo=True,
            hasta__gte=hoy,
            hasta__lte=hoy + timedelta(days=30),
        ).select_related("persona", "cargo"),
        "alertas_hoy": hoy,
        "alertas_licencias": alertas_licencias,
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
        "instrumentos": {
            "titulo": "Instrumentos legales",
            "modelo": TipoInstrumentoLegal,
            "form": TipoInstrumentoLegalForm,
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
        "instrumentos": "personal.change_tipoinstrumentolegal",
        "licencias": "licencias.change_licenciaarticulo",
    }
    if not request.user.has_perm(permisos_seccion[seccion]):
        raise PermissionDenied

    datos = configuracion[seccion]
    objeto_id = request.GET.get("editar")
    objeto_id_valido = _pk_valido(datos["modelo"], objeto_id)
    objeto = (
        datos["modelo"].objects.filter(pk=objeto_id_valido).first()
        if objeto_id_valido
        else None
    )
    if objeto_id and objeto is None:
        messages.error(request, "El registro solicitado no existe.")
        return redirect(f"{reverse('personal:catalogos')}?seccion={seccion}")

    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "guardar":
            objeto_id_enviado = (request.POST.get("objeto_id") or "").strip()
            objeto_pk = _pk_valido(datos["modelo"], objeto_id_enviado)
            objeto = (
                datos["modelo"].objects.filter(pk=objeto_pk).first()
                if objeto_pk
                else None
            )
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
            objeto_id_enviado = (request.POST.get("objeto_id") or "").strip()
            objeto_pk = _pk_valido(datos["modelo"], objeto_id_enviado)
            objeto = (
                datos["modelo"].objects.filter(pk=objeto_pk).first()
                if objeto_pk
                else None
            )
            if objeto:
                campo_activo = datos["campo_activo"]
                if campo_activo:
                    setattr(objeto, campo_activo, False)
                    objeto.save(update_fields=[campo_activo])
                    messages.success(request, "El catálogo se desactivó correctamente.")
                else:
                    try:
                        objeto.delete()
                    except (ProtectedError, RestrictedError):
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
@permission_required("personal.add_designacion", raise_exception=True)
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


@login_required
@permission_required("personal.change_designacion", raise_exception=True)
@require_http_methods(["GET", "POST"])
def editar_designacion(request, designacion_id):
    designacion = get_object_or_404(Designacion, pk=designacion_id)
    if request.method == "POST":
        form = NuevaDesignacionForm(request.POST, instance=designacion)
        if form.is_valid():
            form.save()
            messages.success(request, "La designación docente se modificó correctamente.")
            return redirect(reverse("inicio_personal"))
        messages.error(request, "Revise los datos de la designación.")
    else:
        form = NuevaDesignacionForm(instance=designacion, initial={"persona": designacion.persona_id})

    renovando = request.GET.get("renovar") == "1"
    return render(
        request,
        "personal/nueva_designacion.html",
        {
            "form": form,
            "editando": True,
            "renovando": renovando,
            "paso_inicial": 5 if renovando else 1,
            "designacion": designacion,
        },
    )


@login_required
def autocompletar_legajos(request):
    if not _puede_consultar_legajos(request.user):
        raise PermissionDenied
    termino = request.GET.get("q", "").strip()
    legajos = Persona.objects.filter(activa=True)
    if termino:
        legajos = legajos.filter(
            Q(dni__icontains=termino)
            | Q(apellido_nombre__icontains=termino)
        )
    return JsonResponse(
        {
            "resultados": [
                {"dni": persona.dni, "nombre": persona.apellido_nombre}
                for persona in legajos.order_by("apellido_nombre", "dni")[:20]
            ]
        }
    )


@login_required
def plantilla_importacion_csv(request):
    if not _puede_importar_csv(request.user):
        raise PermissionDenied
    respuesta = HttpResponse(content_type="text/csv; charset=utf-8")
    respuesta["Content-Disposition"] = (
        'attachment; filename="plantilla_personal.csv"'
    )
    respuesta.write("\ufeff")
    escritor = csv.writer(respuesta)
    escritor.writerow(COLUMNAS_CSV_PERSONAL)
    return respuesta


@login_required
@permission_required("personal.change_designacion", raise_exception=True)
def autocompletar_designaciones(request):
    termino = request.GET.get("q", "").strip()
    designaciones = Designacion.objects.select_related(
        "persona",
        "cargo",
        "espacio_curricular",
        "espacio_curricular__carrera",
    )
    if termino:
        designaciones = designaciones.filter(
            Q(persona__dni__icontains=termino)
            | Q(persona__apellido_nombre__icontains=termino)
            | Q(cargo__codigo__icontains=termino)
            | Q(cargo__descripcion__icontains=termino)
            | Q(espacio_curricular__nombre__icontains=termino)
        )
    return JsonResponse(
        {
            "resultados": [
                {
                    "id": designacion.pk,
                    "dni": designacion.persona.dni,
                    "nombre": designacion.persona.apellido_nombre,
                    "cargo": designacion.cargo.descripcion,
                    "espacio": (
                        designacion.espacio_curricular.nombre
                        if designacion.espacio_curricular
                        else ""
                    ),
                    "texto": (
                        f"{designacion.persona.apellido_nombre} - "
                        f"{designacion.persona.dni} - {designacion.cargo.descripcion}"
                    ),
                }
                for designacion in designaciones.order_by(
                    "persona__apellido_nombre", "desde", "pk"
                )[:20]
            ]
        }
    )
