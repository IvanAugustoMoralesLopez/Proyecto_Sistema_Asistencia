# Cambios para cumplir el Documento de Requerimientos v2.0

Este documento lista, requerimiento por requerimiento, qué se cambió en el
sistema para que cumpla la versión 2.0 tal como está escrita. Los que ya
cumplían quedan indicados como "sin cambios".

Las pruebas automáticas pasaron de 546 a 607 y pasan todas
(`python manage.py test`).

## Decisiones tomadas

Cuatro puntos admitían más de una solución. Se resolvieron así:

| Punto | Decisión | Consecuencia |
|---|---|---|
| Alcance | Se corrigieron los cuatro módulos, no solo licencias. | Hay cambios en código de todo el equipo: conviene que cada responsable revise su parte. |
| RF-14 (mensual desde la diaria) | Se agregó un procesamiento mensual nuevo que lee la diaria. La carga de licencias por designación sigue existiendo. | La **planilla mensual IL-01/IL-02** reemplaza al reporte por licencias y al generador de disposiciones anteriores (ver más abajo). |
| RF-07 (una vez por agente) | La pantalla carga una fila por docente; la base sigue guardando un registro por materia. | El dato por materia lo arma el sistema, no el operador, y la planilla mensual lo necesita así. |
| RF-08 (P y PR) | Se cambió al significado del documento y se migraron los datos existentes. | Los P viejos pasan a PR y los PR viejos (presente retirado) pasan a I con una nota. La migración se puede revertir. |

## Módulo 1 · Personal y designaciones (`personal/`)

| Requerimiento | Antes | Cambio |
|---|---|---|
| RF-01, RF-02, RF-04 | Cumplía | Sin cambios. |
| RF-03 | Cumplía | Sin cambios (el CSV ahora también carga horarios, ver RF-06). |
| RF-05 | Faltaba el catálogo de tipos de instrumento legal | Nuevo modelo `TipoInstrumentoLegal` con ABMC en *Catálogos → Instrumentos legales* (baja lógica). Viene cargado con Resolución y Disposición. Alimenta el tipo de norma de la designación y el tipo de instrumento de la licencia. |
| RF-06 | Guardaba sin confirmar y no cargaba horarios | Dos pasos: *Validar archivo* simula la importación completa sin guardar nada y muestra válidas y rechazadas con su motivo; recién *Confirmar e importar* guarda. Columnas nuevas: `horas_lun` a `horas_vie`, `carrera`, `observaciones`. Rechaza tipos de instrumento que no estén en el catálogo. |
| RN-01, RN-02 | Cumplía | Sin cambios. |
| RN-03 | Cumplía, salvo borrado desde el admin | El admin ya no permite borrar personas ni designaciones. |
| RN-09 | Faltaba SIN INICIO | Desde y Hasta aceptan una fecha (dd/mm/aaaa o AAAA-MM-DD) o las cadenas `SIN INICIO` / `SIN TERMINO`, en el formulario y en el CSV. Las pantallas las muestran como texto. Campo nuevo `Designacion.sin_inicio`. |

## Módulo 2 · Asistencia diaria y calendario (`asistencias/`)

| Requerimiento | Antes | Cambio |
|---|---|---|
| RF-07 | Una fila por materia | La planilla rápida muestra **una fila por docente** con un solo selector. Al guardar, la marca se reparte entre sus materias del día con las horas de cada horario. Al corregir un registro, una casilla aplica el mismo cambio a las otras materias del docente ese día. |
| RF-08 | P = Presente, PR = Presente retirado | Catálogo del documento: **P = Permiso, I = Inasistencia, LIC = Licencia médica o especial, LT = Largo tratamiento, PR = Presente**. Migración `0011_marcas_v2_permiso_presente` con conversión de datos y reversa. LIC y LT ya no exigen una licencia otorgada vinculada. |
| RF-09 | Solo cambiaba el estado de justificación | Al recibir el formulario se elige si la I pasa a LIC, LT o P. El cambio alcanza a todas las materias del docente ese día. |
| RF-10 | El feriado bloqueaba la carga y descontaba horas | El calendario es **solo visual**: la pantalla diaria muestra un aviso con fondo de color, pero se puede cargar y nada se descuenta (ni en la licencia, ni en las horas del reporte, ni en el tope anual). Los fines de semana siguen sin carga porque los horarios son de lunes a viernes. |
| RF-11 | Cumplía | Sin cambios (se sumó la corrección por agente de RF-07). |
| RN-06 | Cumplía | En la planilla mensual cada inasistencia injustificada es su propio renglón de un día. |

## Módulo 3 · Procesamiento mensual, licencias e instrumentos legales (`licencias/`)

Nuevo: `licencias/planilla_mensual.py`, modelo `RenglonMensual` y la pantalla
*Planilla mensual IL-01 / IL-02* (`/licencias/planilla/<año>/<mes>/`).

| Requerimiento | Antes | Cambio |
|---|---|---|
| RF-12 / RN-10 | Un renglón por licencia cargada | *Procesar el mes* lee la diaria, detecta los períodos continuos de cada docente y genera un renglón por **cada** materia que dictaba en esos días, aunque el operador haya marcado una sola. |
| RF-13 | Cumplía, pero descontaba feriados | Las horas salen del horario semanal de cada designación. Sin descuento de feriados. |
| RF-14 | Circuito invertido; recortaba al mes | Desde y Hasta son el inicio y el fin del período continuo de la diaria. Un fin de semana o un día sin clase no corta el período; un día presente sí. Si cruza de mes, ambos meses muestran el intervalo completo con las horas de cada mes. |
| RF-15 | Selector solo en el alta; el código no se veía | En la planilla mensual cada renglón tiene el desplegable de artículos (filtrado por situación de revista). Al elegirlo se muestra el COD.LIC. y, al guardar, el renglón pasa a IL-01 o IL-02. Las otras materias del mismo período toman el mismo artículo. El código también se ve en el asistente del alta de licencia. |
| RF-16 / RN-11 | Cumplía | *Emitir disposiciones* da un único número por docente y período, correlativo y en orden alfabético por apellido, continuando la numeración del año (compartida con las licencias). Columna de Resolución del M.E.C.C.yT. como dato externo. |
| RN-04 / RN-05 | Cumplía | Sin artículo, I y P van a IL-02, LT a IL-01 y LIC queda en "Pendientes de imputar" hasta que se elige el artículo. |
| RN-07 / RN-08 | Solo al emitir la disposición | Cada renglón nace con Oficina = 1452 (parámetro del sistema) y Año = año del período, editables en la planilla. El alta de licencia también los trae precargados. |
| INC-01 (diferido) | — | Se agregó una exportación CSV básica de los cuadros. La impresión oficial sigue diferida. |
| INC-02 (diferido) | — | Si la diaria cambia después de emitida una disposición, el renglón no se borra: queda marcado "Revisar" para corregirlo a mano. |

**Reporte por licencias y generador de disposiciones anteriores: retirados.** La
planilla mensual los reemplaza. Se sacaron del menú y se borraron su código y sus
plantillas; sus direcciones redirigen a la planilla del mismo mes, para que los
enlaces guardados no den error. La emisión de disposiciones quedó en un solo lugar
(la planilla y el comando `emitir_disposiciones`, que ahora la usa), así una misma
licencia no puede recibir dos números.

**Faltas sin formulario.** Arriba de los cuadros, un recuadro rojo lista las
inasistencias del mes que todavía esperan el papel, una fila por docente y día,
con dos botones: *Recibir formulario* (abre Recepción de formularios para pasar la
I a P, LIC o LT) y *Cargar licencia* (abre Nueva licencia con el docente y la fecha
cargados). Al guardar, se vuelve a la planilla. Una inasistencia sin formulario no
admite artículo (RF-09: primero el papel, después la imputación).

**Disposiciones del mes.** Debajo de la lista a emitir se ven las disposiciones ya
emitidas, agrupadas por número con todas sus materias (RN-11).

## Módulo 4 · Consultas, alertas, usuarios y auditoría (`reportes/`)

| Requerimiento | Antes | Cambio |
|---|---|---|
| RF-17 | Sin selector de mes | Filtro *Mes* en Consultas que completa Desde y Hasta. |
| RF-18 | Solo topes por artículo | Nueva pestaña *Alertas → Inasistencias y permisos*: total acumulado por agente en el ciclo lectivo (I y P, un día por agente aunque tenga varias materias), con estado Normal / Próximo al límite / Límite agotado y umbral configurable. El docente en alerta también se marca en la planilla rápida. El límite anual es un parámetro nuevo (*Parámetros*); el documento no fija el número, así que trae 6 días como valor provisorio. |
| RF-19 | Cumplía | Los tres roles reciben los permisos del catálogo nuevo (migración `reportes 0005`). |
| RF-20 | Cumplía, salvo historial de designaciones sin usuario | El historial de designaciones guarda el usuario. Los renglones mensuales guardan quién y cuándo los creó y modificó, y procesar y emitir quedan en la bitácora. |

## Otros cambios

- `datos_prueba.sql`: marcas con el significado v2.0 y columnas que faltaban (`plan_vigente`, `es_suplencia`, `plazo_indeterminado`, `sin_inicio`); antes dependía de que MariaDB completara esos valores solo. Se verificó que carga completa y que octubre genera la planilla mensual.
- `settings.py`: `DEBUG`, `SECRET_KEY` y `ALLOWED_HOSTS` se leen del `.env` (con valores de desarrollo por defecto). Ver `example.env`.
- El comprimido no incluye `.env` ni `.venv`: después de descomprimir hay que copiar `example.env` como `.env` y recrear el entorno virtual (ver README).

## Migraciones nuevas

| App | Migración | Qué hace |
|---|---|---|
| asistencias | `0011_marcas_v2_permiso_presente` | Catálogo P/PR del documento y conversión de los registros existentes (reversible). |
| personal | `0004_instrumentos_legales_y_sin_inicio` | Catálogo de instrumentos legales y vigencia SIN INICIO. |
| personal | `0005_historial_usuario` | Usuario en el historial de designaciones. |
| licencias | `0011_renglon_mensual` | Tabla de la planilla mensual. |
| reportes | `0005_rol_instrumentos_legales` | Permisos del catálogo nuevo para los tres roles. |
| reportes | `0006_limite_inasistencias` | Parámetro del límite anual de inasistencias. |

## Qué comprobar a mano después de instalar

1. `python manage.py migrate` termina sin errores sobre MariaDB. Esta versión se probó con SQLite, no con MariaDB.
2. Cargar `datos_prueba.sql`, entrar como `bedelia1` y abrir *Planilla mensual IL-01 / IL-02* de octubre de 2026. Tocar *Procesar el mes* tiene que generar 14 renglones.
3. En la planilla rápida de un día con un docente de varias materias, elegir una sola marca y revisar en el historial que se crearon los registros de cada materia.
4. Cargar un feriado en el calendario y comprobar que ese día se puede cargar asistencia y que aparece el aviso.
