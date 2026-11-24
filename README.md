# Sistema de Gestión de Asistencia y Licencias Docentes

Trabajo Intercátedra · IESETyFP · Tecnicatura Superior en Desarrollo de Software (3° año) · Grupo 3.

Sistema web hecho con Django que controla la asistencia, las licencias y la situación de revista del personal docente de un instituto, e imprime los informes mensuales de licencias (planillas IL-01 e IL-02).

Pantallas principales:

1. Personal, legajos y designaciones.
2. Asistencia diaria y calendario escolar.
3. Licencias, planilla mensual IL-01 / IL-02 y disposiciones.
4. Consultas, alertas y bitácora de auditoría.

## Requisitos

- Python 3.14.4 o superior (según `requirements.txt`).
- MariaDB o MySQL (se probó con MariaDB 13.0.2).
- Git.
- En Windows, `mysqlclient` puede necesitar herramientas de compilación si no hay una versión ya compilada para tu Python.

## Instalación

### 1. Clonar el repositorio

```
git clone https://github.com/IvanAugustoMoralesLopez/Proyecto_Sistema_Asistencia.git
cd Proyecto_Sistema_Asistencia
```

### 2. Crear el entorno virtual e instalar las dependencias

En Windows (PowerShell):

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

En Linux o macOS:

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Crear la base de datos

Si el servicio de MariaDB está apagado, iniciarlo (en Windows: `net start MariaDB`). Después, desde la consola de MariaDB o MySQL con un usuario administrador:

```sql
CREATE DATABASE asistencia CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'asistencia'@'localhost' IDENTIFIED BY 'elegí_una_clave';
GRANT ALL PRIVILEGES ON asistencia.* TO 'asistencia'@'localhost';
FLUSH PRIVILEGES;
SHOW VARIABLES LIKE 'port';
```

El último comando muestra el puerto que usa tu servidor. Este proyecto está pensado para el puerto **3307**, que se elige al instalar MariaDB (el puerto por defecto del instalador es 3306). Lo necesitás en el paso siguiente.

> El archivo `crear mariadb 13.0.2(...).sql` del repositorio hace lo mismo, pero concede permisos sobre todas las bases (`*.*`) y trae una clave de ejemplo. Usá la versión de arriba y cambiá la clave.

### 4. Configurar el archivo `.env`

Copiá `example.env` como `.env` en la raíz del proyecto y completá los valores:

```
DB_NAME=asistencia
DB_USER=asistencia
DB_PASSWORD=la_clave_que_elegiste
DB_HOST=127.0.0.1
DB_PORT=3307

# Opcionales
DJANGO_DEBUG=1
DJANGO_SECRET_KEY=
DJANGO_ALLOWED_HOSTS=
```

`DJANGO_DEBUG=1` es para desarrollo. Para la puesta en marcha poné `DJANGO_DEBUG=0`, una `DJANGO_SECRET_KEY` propia y el nombre del servidor en `DJANGO_ALLOWED_HOSTS`.

El puerto es **3307**, el mismo que `settings.py` usa por defecto. Si tu MariaDB quedó en otro puerto (por ejemplo 3306), poné el que mostró `SHOW VARIABLES LIKE 'port'`.

**El archivo `.env` está en `.gitignore`: nunca lo subas ni lo compartas.**

### 5. Crear las tablas y los roles

```
python manage.py migrate
python manage.py sincronizar_roles
```

`migrate` crea las tablas, las marcas de asistencia y los tres roles. Las marcas siguen el Documento de Requerimientos v2.0: **P = Permiso, I = Inasistencia, LIC = Licencia médica o especial, LT = Largo tratamiento, PR = Presente**. Si tu base ya tenía registros con el significado anterior (P = Presente, PR = Presente retirado), la migración `asistencias 0011` los convierte solos: los P pasan a PR y los PR pasan a I con una nota en las observaciones. También crea el catálogo de tipos de instrumento legal (Resolución y Disposición). `sincronizar_roles` deja los permisos de cada rol al día.

### 6. Cargar datos de prueba (opcional)

El archivo `datos_prueba.sql` carga datos ficticios: 20 docentes, 22 designaciones, 12 licencias, feriados 2026, registros de asistencia de octubre 2026 y 9 usuarios. Antes tenés que haber corrido `migrate` (paso 5).

Ejecutalo completo como script SQL sobre la base `asistencia` (por ejemplo con "Execute SQL File" en Navicat o "Execute SQL Script" en DBeaver, no una sentencia suelta). Está pensado para poder volver a ejecutarse sin duplicar datos. El bloque de limpieza al final del archivo sirve para borrarlos.

### 7. Uso mensual (cuadros IL-01 / IL-02)

1. Todos los días se carga la asistencia en la **planilla rápida**, ...
2. Al recibir el formulario en papel, ...
3. A fin de mes, ...
4. Se elige el artículo de cada renglón ...

Para mirar el mes completo, en **Asistencia del día** está la pestaña **Mes**: una fila por docente y una columna por día, como la hoja «ASISTENCIA» del Excel. Se puede filtrar por carrera, exportar a CSV e imprimir. Un «·» marca un día con clase que todavía no se cargó.

El detalle de qué cambió para cumplir cada requerimiento está en `CAMBIOS_REQUERIMIENTOS_v2.md`.

### 8. Levantar el servidor
```
python manage.py runserver
```

Abrí http://127.0.0.1:8000/ e ingresá con alguno de los usuarios de prueba. Si no cargaste los datos de prueba, creá un administrador con `python manage.py createsuperuser`.

## Usuarios de prueba

Contraseña de todos: `Prueba2026!`. **Cambiala antes de usar el sistema con datos reales.**

| Rol | Usuarios | Qué puede hacer |
|---|---|---|
| Bedelía | `bedelia1` a `bedelia3` | Todos los permisos: asistencia (cargar, corregir, validar, cerrar jornada y mes), formularios en papel, licencias, calendario escolar, legajos y designaciones, consultas, alertas, bitácora, parámetros, usuarios y catálogos. |
| Secretaría | `secretaria1` a `secretaria3` | Todos los permisos: asistencia (cargar, corregir, validar, cerrar jornada y mes), formularios en papel, licencias, calendario escolar, legajos y designaciones, consultas, alertas, bitácora, parámetros, usuarios y catálogos. |
| Subsecretaría | `subsecretaria1` a `subsecretaria3` | Todos los permisos: asistencia (cargar, corregir, validar, cerrar jornada y mes), formularios en papel, licencias, calendario escolar, legajos y designaciones, consultas, alertas, bitácora, parámetros, usuarios y catálogos. |

Los tres roles tienen los mismos permisos (los de Subsecretaría). Se definen en `reportes/roles.py`; si se cambian, hay que volver a correr `python manage.py sincronizar_roles`.

## Tests

```
python manage.py test
```

Tienen que pasar todos antes de integrar cambios a `main`.

## Estructura

```
config/       configuración de Django (settings, urls)
personal/     legajos, designaciones, catálogos, importación CSV
asistencias/  registro diario, planilla rápida, cierres, calendario escolar
licencias/    licencias otorgadas, planilla mensual IL-01/IL-02, disposiciones
reportes/     consultas, alertas, bitácora, usuarios, parámetros, roles
templates/    base.html y páginas compartidas (403, 404, 500)
static/       estilos propios (static/css)
```

## Equipo

| Integrante | Rol |
|---|---|
| Iván Morales López | Desarrollo back (módulo Asistencias) |
| Lucas Gabriel Montenegro | Líder de gestión y desarrollo back (módulo Personal) |
| Enzo Sebastián Cañete | Desarrollo back y consultor (módulo Licencias) |
| Lucas Nahuel Juárez Irigoyen | Desarrollo back y sub encargado de base de datos (módulo Reportes) |
| Benjamín Ariel Loto Rivarola | Desarrollo front y documentación |
| Abril Antonella Carmona | Desarrollo front y manual de usuario |
