-- =====================================================================
--  Base de datos: planilla_personal   (VERSIÓN AMPLIADA)
--  Modelo a partir de la planilla estadística del personal 2026
--  (nivel superior): docentes y personal no docente (p. ej. bedeles),
--  con licencias por artículo y asistencia diaria / mensual.
--
--  Ampliación: ahora también contempla los formularios de la Provincia
--  del Chaco:
--    · Formulario Nº 1  - Ingreso de Datos del Agente
--    · Formulario DP-01 - Disposición de alta de interinos y suplentes /
--                         comunicación de ingreso definitivo de titulares
--    · Formulario DL-01 - Disposición de licencia / permiso / inasistencia
--
--  Motor: MySQL 8.0.16+ (o MariaDB 10.2+) por los CHECK
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Creación de la base de datos
-- ---------------------------------------------------------------------
DROP DATABASE IF EXISTS planilla_personal;

CREATE DATABASE planilla_personal
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE planilla_personal;

-- ---------------------------------------------------------------------
-- 2. Entidades principales
-- ---------------------------------------------------------------------

-- PERSONAL: la persona, sea docente o no docente.
--   Planilla: D.N.I, DOCENTE, SEXO.
--   Formulario Nº 1: apellido, nombres, documento (número y tipo), sexo,
--   fecha de nacimiento, estado civil, nacionalidad, Nº de inscripción
--   D.G.I. y D.G.R., domicilio y teléfono.
--   Nota: en los formularios, si es mujer el apellido es el de SOLTERA;
--   se guarda en `apellido`.
--   apellido_nombre es una columna calculada, para que las consultas de
--   la versión anterior sigan funcionando.
CREATE TABLE personal (
    dni              INT UNSIGNED  NOT NULL,           -- Documento de identidad: Número
    tipo_documento   VARCHAR(10)   NOT NULL DEFAULT 'DNI',  -- Documento de identidad: Tipo
    apellido         VARCHAR(80)   NOT NULL,
    nombres          VARCHAR(80)   NOT NULL,
    apellido_nombre  VARCHAR(165)
        GENERATED ALWAYS AS (CONCAT(apellido, ', ', nombres)) STORED,
    sexo             CHAR(1)       NULL,
    fecha_nacimiento DATE          NULL,               -- Día / Mes / Año
    estado_civil     VARCHAR(20)   NULL,
    nacionalidad     VARCHAR(40)   NULL,
    nro_dgi          VARCHAR(20)   NULL,               -- Nº de inscripción D.G.I.
    nro_dgr          VARCHAR(20)   NULL,               -- Nº de inscripción D.G.R.
    -- Datos del domicilio
    domicilio_calle  VARCHAR(120)  NULL,               -- Calle y número o nomenclatura del barrio
    barrio           VARCHAR(80)   NULL,               -- Nombre del barrio
    localidad        VARCHAR(80)   NULL,
    codigo_postal    VARCHAR(10)   NULL,
    provincia        VARCHAR(60)   NULL,
    telefono         VARCHAR(30)   NULL,
    PRIMARY KEY (dni),
    CONSTRAINT chk_personal_sexo CHECK (sexo IN ('F', 'M', 'X'))
) ENGINE=InnoDB;

-- INGRESO_AGENTE: el Formulario Nº 1 como trámite (presentación, recepción
-- y sectores reservados). Una persona puede tener más de un trámite
-- (p. ej. una actualización de datos).
CREATE TABLE ingreso_agente (
    id                       INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    dni                      INT UNSIGNED  NOT NULL,
    documentacion_adjunta    VARCHAR(255)  NULL,   -- "Adjunto la siguiente documentación"
    lugar_presentacion       VARCHAR(80)   NULL,   -- Lugar y fecha de presentación
    fecha_presentacion       DATE          NULL,
    -- A cumplimentar por el encargado de personal de la unidad administrativa
    lugar_recepcion          VARCHAR(80)   NULL,   -- Lugar y fecha de recepción
    fecha_recepcion          DATE          NULL,
    responsable_recepcion    VARCHAR(120)  NULL,   -- Firma y sello responsable
    jurisdiccion             VARCHAR(40)   NULL,
    escalafon                VARCHAR(40)   NULL,
    item_nivel               VARCHAR(40)   NULL,   -- Ítem/Nivel
    modalidad                VARCHAR(40)   NULL,
    oficina                  VARCHAR(40)   NULL,
    -- Reservado para el encargado de verificación y control del S.A.G.P.
    sagp_fecha_ingreso_bd    DATE          NULL,   -- Fecha de ingreso a bases de datos
    sagp_cargo               VARCHAR(80)   NULL,   -- "Cargó" (quién cargó los datos)
    -- Reservado para la D.G.P.
    dgp_fecha_recibido       DATE          NULL,   -- Recibido en D.G.P.
    dgp_recibio              VARCHAR(80)   NULL,   -- "Recibió"
    PRIMARY KEY (id),
    CONSTRAINT fk_ingreso_personal
        FOREIGN KEY (dni) REFERENCES personal (dni)
        ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB;

-- UNIDAD_EDUCATIVA: establecimiento donde se ejerce el cargo
-- (campos de encabezado de DP-01 y DL-01).
-- Supuesto: código de oficina, código de anexo, nivel/modalidad, categoría,
-- zona y localidad o paraje son datos del establecimiento.
CREATE TABLE unidad_educativa (
    id               INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    numero           VARCHAR(20)   NOT NULL,   -- Número de la unidad educativa
    descripcion      VARCHAR(120)  NOT NULL,   -- Descripción de la unidad educativa
    codigo_oficina   VARCHAR(10)   NULL,       -- Código de oficina
    codigo_anexo     VARCHAR(10)   NULL,       -- Código de anexo
    nivel_modalidad  VARCHAR(60)   NULL,       -- Nivel/Modalidad
    categoria        VARCHAR(20)   NULL,       -- Categoría
    zona             VARCHAR(30)   NULL,       -- Zona
    localidad_paraje VARCHAR(80)   NULL,       -- Localidad o paraje
    PRIMARY KEY (id),
    UNIQUE KEY uq_unidad (numero, codigo_anexo)
) ENGINE=InnoDB;

-- CARGO: catálogo de cargos (columnas COD y DESCRIPCION de la planilla)
-- En la planilla: 166 = «hs catedras» (titulares, interinos y suplentes),
-- 165 = BEDEL, 155 / 150 = SECRETARIA, DR DE ESTUDIO, etc.
-- Un mismo código puede aparecer con descripciones distintas, por eso la
-- clave es un id y lo único es el par (cod, descripcion).
-- es_docente = TRUE  -> el cargo se ejerce sobre un espacio curricular
-- es_docente = FALSE -> cargo no docente (bedel, etc.), sin espacio curricular
CREATE TABLE cargo (
    id           INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    cod          VARCHAR(10)   NOT NULL,
    descripcion  VARCHAR(120)  NOT NULL,
    es_docente   BOOLEAN       NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uq_cargo (cod, descripcion)
) ENGINE=InnoDB;

-- CARRERA: carrera con su plan de estudio (campo "Plan de estudio" de DP-01)
CREATE TABLE carrera (
    id            INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    nombre        VARCHAR(120)  NOT NULL,
    plan_estudio  VARCHAR(60)   NOT NULL,
    anio_plan     SMALLINT      NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_carrera (nombre, plan_estudio, anio_plan)
) ENGINE=InnoDB;

-- ESPACIO_CURRICULAR: cada materia pertenece a una carrera (1:N)
-- (campo "Asignatura" de DP-01 y DL-01)
CREATE TABLE espacio_curricular (
    id          INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    nombre      VARCHAR(120)  NOT NULL,
    carrera_id  INT UNSIGNED  NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_espacio_carrera (carrera_id, nombre),
    CONSTRAINT fk_espacio_carrera
        FOREIGN KEY (carrera_id) REFERENCES carrera (id)
        ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB;

-- ESPECIALIDAD: títulos / especialidades.
--   · N:M con personal (título que posee la persona).
--   · 1:N con designacion (campo "Especialidad" del bloque de cargo de DP-01).
CREATE TABLE especialidad (
    id      INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    titulo  VARCHAR(120)  NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_especialidad_titulo (titulo)
) ENGINE=InnoDB;

CREATE TABLE personal_especialidad (
    dni              INT UNSIGNED  NOT NULL,
    especialidad_id  INT UNSIGNED  NOT NULL,
    PRIMARY KEY (dni, especialidad_id),
    CONSTRAINT fk_pe_personal
        FOREIGN KEY (dni) REFERENCES personal (dni)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_pe_especialidad
        FOREIGN KEY (especialidad_id) REFERENCES especialidad (id)
        ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB;

-- MOTIVO: catálogo de "Código de motivo" (5 dígitos) de DP-01.
--   · Titulares e interinos: motivo del alta.
--   · Suplentes: motivo por el que se reemplaza a otra persona.
-- Los códigos reales hay que cargarlos desde el instructivo del formulario.
CREATE TABLE motivo (
    id           INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    codigo       CHAR(5)       NOT NULL,
    descripcion  VARCHAR(200)  NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_motivo_codigo (codigo),
    CONSTRAINT chk_motivo_codigo CHECK (codigo REGEXP '^[0-9]{5}$')
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 3. Catálogo de códigos y artículos de licencia (2.ª hoja de la planilla)
--    Cada código de licencia (01.02.01, 2.13.3…) es único y pertenece a una
--    situación de revista (Titular / Interino / Suplente). Un mismo artículo
--    (p. ej. 309 B-2) puede tener varios códigos (con goce / con 50% de haberes).
--    categoria_informe agrupa las licencias como en el informe mensual
--    (columnas ENF COMUN / LARGO TRAT / OTROS).
--
--    NUEVO: `clase` distingue si el código es de LICENCIA, PERMISO o
--    INASISTENCIA, que son los tres códigos que pide el DL-01
--    ("Código de licencia / permiso / inasistencia", con su artículo y
--    descripción). La forma de pago del DL-01 (con goce / sin goce /
--    con 50 % de haberes) es `goce_haberes`.
-- ---------------------------------------------------------------------
CREATE TABLE licencia_articulo (
    id                 INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    cod_licencia       VARCHAR(12)   NOT NULL,   -- COD.LIC. (01.02.01, 2.13.3…)
    articulo           VARCHAR(20)   NOT NULL,   -- ART. (309 B-2), 340 B)…)
    clase              ENUM('Licencia','Permiso','Inasistencia')
                       NOT NULL DEFAULT 'Licencia',
    tipo_licencia      VARCHAR(120)  NOT NULL,   -- ENFERMEDAD O LESION COMUN, etc. (Descripción)
    categoria_informe  ENUM('Enfermedad común','Largo tratamiento','Otros')
                       NOT NULL DEFAULT 'Otros',
    sit_rev            VARCHAR(20)   NOT NULL,   -- Titular / Interino / Suplente
    goce_haberes       VARCHAR(30)   NOT NULL,   -- Con goce / Sin goce / Con 50% de haberes
    autoridad          VARCHAR(30)   NOT NULL,   -- Director, Ministro, Supervisor…
    plazo              VARCHAR(200)  NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_licencia_cod (cod_licencia),
    UNIQUE KEY uq_articulo_id_sit (id, sit_rev),
    CONSTRAINT chk_articulo_sit_rev
        CHECK (sit_rev IN ('Titular', 'Interino', 'Suplente'))
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 4. Tabla intermedia: DESIGNACION (personal <-> cargo <-> espacio curricular)
--    Cada fila = un cargo que ejerce una persona (un bloque de cargo del
--    DP-01 / DL-01).
--    - Docentes: espacio_curricular_id completo.
--    - Bedeles y otro personal no docente: espacio_curricular_id NULL.
--    - Suplentes: suple_licencia_id apunta a la licencia que cubren y
--      reemplazado_designacion_id al cargo de la persona reemplazada
--      ("Datos del reemplazado" del DP-01: DNI, sexo, apellido, nombres
--      salen de personal vía esa designación).
--      Sus norma_* / desde / hasta son la resolución del suplente y el
--      inicio y fin de la suplencia.
--    Regla a validar en la aplicación: si cargo.es_docente = TRUE,
--    espacio_curricular_id no debería ser NULL; y solo los suplentes
--    llevan suple_licencia_id / reemplazado_designacion_id.
--    Fecha de alta (DP-01 "Desde / Hasta") = desde / hasta.
-- ---------------------------------------------------------------------
CREATE TABLE designacion (
    id                        INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    dni                       INT UNSIGNED  NOT NULL,
    cargo_id                  INT UNSIGNED  NOT NULL,   -- Código de cargo/Hs + Descripción
    espacio_curricular_id     INT UNSIGNED  NULL,       -- Asignatura (y plan de estudio vía carrera)
    unidad_educativa_id       INT UNSIGNED  NOT NULL,   -- Unidad educativa (oficina, anexo, nivel, zona…)
    especialidad_id           INT UNSIGNED  NULL,       -- Especialidad del cargo (DP-01)
    suple_licencia_id         INT UNSIGNED  NULL,       -- licencia que cubre (solo suplentes)
    reemplazado_designacion_id INT UNSIGNED NULL,       -- cargo de la persona reemplazada (solo suplentes)
    sit_rev                   VARCHAR(20)   NOT NULL,   -- SIT.REV. (Titular / Interino / Suplente)
    -- Datos del cargo en la unidad educativa
    anio_curso                VARCHAR(10)   NULL,       -- "Año"
    division_seccion          VARCHAR(20)   NULL,       -- División o sección
    turno                     VARCHAR(20)   NULL,
    hs_catedra                TINYINT UNSIGNED NULL,    -- Hs. cátedra (total del cargo)
    jornada                   VARCHAR(30)   NULL,       -- Jornada (DP-01)
    -- Disposición de alta (DP-01)
    disp_alta_nro             VARCHAR(20)   NULL,       -- Disposición de alta Nº (no se consigna para titulares)
    sello_regional_as         VARCHAR(30)   NULL,       -- Sello regional (A.S. Nº A)
    motivo_id                 INT UNSIGNED  NULL,       -- Código de motivo + descripción
    motivo_instrumento_legal  VARCHAR(40)   NULL,       -- Instrumento legal Nº del motivo
    -- Norma de la designación (planilla)
    norma_tipo                VARCHAR(30)   NULL,       -- Tipo (resolución, etc.)
    norma_nro                 VARCHAR(20)   NULL,       -- Nº
    norma_anio                SMALLINT      NULL,       -- Año
    org_emisor                VARCHAR(60)   NULL,       -- Org. Emisor
    desde                     DATE          NOT NULL,
    hasta                     DATE          NULL,
    pof                       VARCHAR(30)   NULL,
    anio_pof                  SMALLINT      NULL,
    novedad                   VARCHAR(40)   NULL,       -- AFECTACION DOCENTE, LIC DE ASCENSO, SUMARIO…
    observaciones             TEXT          NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_designacion (dni, cargo_id, espacio_curricular_id, desde),
    UNIQUE KEY uq_designacion_id_sit (id, sit_rev),
    CONSTRAINT chk_designacion_sit_rev
        CHECK (sit_rev IN ('Titular', 'Interino', 'Suplente')),
    CONSTRAINT chk_designacion_fechas
        CHECK (hasta IS NULL OR hasta >= desde),
    CONSTRAINT fk_designacion_personal
        FOREIGN KEY (dni) REFERENCES personal (dni)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_designacion_cargo
        FOREIGN KEY (cargo_id) REFERENCES cargo (id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_designacion_espacio
        FOREIGN KEY (espacio_curricular_id) REFERENCES espacio_curricular (id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_designacion_unidad
        FOREIGN KEY (unidad_educativa_id) REFERENCES unidad_educativa (id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_designacion_especialidad
        FOREIGN KEY (especialidad_id) REFERENCES especialidad (id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_designacion_motivo
        FOREIGN KEY (motivo_id) REFERENCES motivo (id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_designacion_reemplazado
        FOREIGN KEY (reemplazado_designacion_id) REFERENCES designacion (id)
        ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB;

-- LICENCIA_OTORGADA: cada vez que una persona (p. ej. un titular) presenta
-- una licencia, permiso o inasistencia (un bloque del DL-01).
-- Guarda el artículo, la disposición y el inicio y fin.
-- sit_rev se repite a propósito: las claves compuestas obligan a que el
-- artículo elegido corresponda a la situación de revista del cargo.
-- El tipo (licencia / permiso / inasistencia) lo da licencia_articulo.clase.
-- Un DL-01 con varios bloques = varias filas con la misma disposición.
CREATE TABLE licencia_otorgada (
    id                INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    designacion_id    INT UNSIGNED  NOT NULL,   -- cargo de quien se ausenta
    articulo_id       INT UNSIGNED  NOT NULL,
    sit_rev           VARCHAR(20)   NOT NULL,
    disp_tipo         VARCHAR(20)   NULL,       -- INSTRUMENTO LEGAL: tipo (disposición, resolución)
    disp_oficina      VARCHAR(10)   NULL,       -- INSTRUMENTO LEGAL: oficina
    disp_numero       VARCHAR(20)   NULL,       -- Disposición de licencia/permiso/inasistencia Nº
    disp_anio         SMALLINT      NULL,       -- INSTRUMENTO LEGAL: año
    sello_regional_as VARCHAR(30)   NULL,       -- Sello regional (A.S. Nº A) del DL-01
    justifica         BOOLEAN       NULL,       -- "Justifica: Sí / No" (para inasistencias)
    desde             DATE          NOT NULL,   -- Período de licencia: desde
    hasta             DATE          NULL,       -- Período de licencia: hasta
    observaciones     TEXT          NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_licencia_id_designacion (id, designacion_id),
    CONSTRAINT chk_licencia_fechas
        CHECK (hasta IS NULL OR hasta >= desde),
    CONSTRAINT fk_licencia_designacion
        FOREIGN KEY (designacion_id, sit_rev)
        REFERENCES designacion (id, sit_rev)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_licencia_articulo
        FOREIGN KEY (articulo_id, sit_rev)
        REFERENCES licencia_articulo (id, sit_rev)
        ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB;

-- La designación del suplente apunta a la licencia que cubre
-- (se agrega acá porque licencia_otorgada se crea después de designacion)
ALTER TABLE designacion
    ADD CONSTRAINT fk_designacion_suple_licencia
        FOREIGN KEY (suple_licencia_id) REFERENCES licencia_otorgada (id)
        ON UPDATE CASCADE ON DELETE SET NULL;

-- ---------------------------------------------------------------------
-- 5. Horario y asistencia
-- ---------------------------------------------------------------------

-- HORARIO: una fila por día de cada designación (en vez de columnas lunes..viernes)
CREATE TABLE horario (
    id              INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    designacion_id  INT UNSIGNED  NOT NULL,
    dia             ENUM('Lunes','Martes','Miércoles','Jueves','Viernes') NOT NULL,
    horas_catedra   TINYINT UNSIGNED NULL,   -- NULL = día marcado con X (cargo sin horas cátedra)
    hora_inicio     TIME          NULL,
    hora_fin        TIME          NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_horario (designacion_id, dia),
    CONSTRAINT chk_horario_horas
        CHECK (hora_inicio IS NULL OR hora_fin IS NULL OR hora_fin > hora_inicio),
    CONSTRAINT fk_horario_designacion
        FOREIGN KEY (designacion_id) REFERENCES designacion (id)
        ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB;

-- ASISTENCIA: una fila por designación y día (carga diaria).
-- El informe mensual se obtiene agrupando estas filas (ver sección 8).
--   Presente -> 0 horas de inasistencia, sin licencia
--   Ausente  -> horas_inasistidas > 0 (todas o algunas), sin licencia
--   Licencia -> horas_inasistidas > 0 y licencia_otorgada_id obligatorio
-- La clave compuesta (licencia_otorgada_id, designacion_id) obliga a que
-- la licencia sea del mismo cargo al que se le carga la asistencia.
CREATE TABLE asistencia (
    id                    INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    designacion_id        INT UNSIGNED  NOT NULL,
    fecha                 DATE          NOT NULL,
    estado                ENUM('Presente','Ausente','Licencia') NOT NULL,
    horas_inasistidas     TINYINT UNSIGNED NOT NULL DEFAULT 0,
    licencia_otorgada_id  INT UNSIGNED  NULL,
    observaciones         TEXT          NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_asistencia (designacion_id, fecha),
    CONSTRAINT chk_asistencia_estado CHECK (
           (estado = 'Presente' AND horas_inasistidas = 0 AND licencia_otorgada_id IS NULL)
        OR (estado = 'Ausente'  AND horas_inasistidas > 0 AND licencia_otorgada_id IS NULL)
        OR (estado = 'Licencia' AND horas_inasistidas > 0 AND licencia_otorgada_id IS NOT NULL)
    ),
    CONSTRAINT fk_asistencia_designacion
        FOREIGN KEY (designacion_id) REFERENCES designacion (id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_asistencia_licencia
        FOREIGN KEY (licencia_otorgada_id, designacion_id)
        REFERENCES licencia_otorgada (id, designacion_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB;

-- =====================================================================
-- 7. Datos de prueba FICTICIOS (podés borrar esta sección)
--    Los códigos y descripciones de cargo y los artículos de licencia siguen
--    la planilla; las personas, unidades, motivos y el resto de los datos
--    son inventados.
-- =====================================================================
INSERT INTO personal
    (dni, tipo_documento, apellido, nombres, sexo, fecha_nacimiento, estado_civil,
     nacionalidad, nro_dgi, nro_dgr, domicilio_calle, barrio, localidad,
     codigo_postal, provincia, telefono) VALUES
    (10000001, 'DNI', 'Pérez',  'Ana',    'F', '1980-05-12', 'Casada',  'Argentina',
        '27-10000001-4', '1000001', 'Calle 1 Nº 100', 'Centro',     'Resistencia', '3500', 'Chaco', '3624-000001'),
    (10000002, 'DNI', 'Gómez',  'Carlos', 'M', '1985-09-30', 'Soltero', 'Argentina',
        '20-10000002-5', '1000002', 'Calle 2 Nº 200', 'Villa Sur',  'Resistencia', '3500', 'Chaco', '3624-000002'),
    (10000003, 'DNI', 'López',  'María',  'F', '1990-01-20', 'Soltera', 'Argentina',
        '27-10000003-6', '1000003', 'Calle 3 Nº 300', 'Norte',      'Barranqueras','3503', 'Chaco', '3624-000003');

INSERT INTO ingreso_agente
    (dni, documentacion_adjunta, lugar_presentacion, fecha_presentacion,
     lugar_recepcion, fecha_recepcion, jurisdiccion, escalafon, item_nivel,
     modalidad, oficina, sagp_fecha_ingreso_bd, sagp_cargo, dgp_fecha_recibido, dgp_recibio) VALUES
    (10000001, 'Copia de DNI y título', 'Resistencia', '2024-02-20',
     'Resistencia', '2024-02-21', 'Educación', 'Docente', 'Nivel 1',
     'Superior', '0001', '2024-02-28', 'Empleado SAGP', '2024-03-01', 'Empleado DGP');

INSERT INTO unidad_educativa
    (numero, descripcion, codigo_oficina, codigo_anexo, nivel_modalidad, categoria, zona, localidad_paraje) VALUES
    ('101', 'Instituto Superior de Formación Técnica (ficticio)', '0001', '00', 'Superior', '1ra', 'Urbana', 'Resistencia');

INSERT INTO cargo (cod, descripcion, es_docente) VALUES
    ('166', 'hs catedras', TRUE),    -- id 1
    ('165', 'BEDEL',       FALSE),   -- id 2
    ('155', 'SECRETARIA',  FALSE);   -- id 3

INSERT INTO carrera (nombre, plan_estudio, anio_plan) VALUES
    ('Tecnicatura en Desarrollo de Software', 'Plan 2020', 2020),
    ('Tecnicatura en Redes',                  'Plan 2019', 2019);

INSERT INTO espacio_curricular (nombre, carrera_id) VALUES
    ('Programación III',      1),
    ('Base de Datos',         1),
    ('Redes de Computadoras', 2);

INSERT INTO especialidad (titulo) VALUES
    ('Analista de Sistemas'),      -- id 1
    ('Técnico en Redes');          -- id 2

INSERT INTO personal_especialidad (dni, especialidad_id) VALUES
    (10000001, 1),
    (10000002, 1),
    (10000002, 2);

-- Códigos de motivo FICTICIOS (los reales están en el instructivo)
INSERT INTO motivo (codigo, descripcion) VALUES
    ('00001', 'Vacante (ficticio)'),
    ('00002', 'Licencia del titular (ficticio)');

INSERT INTO licencia_articulo
    (cod_licencia, articulo, clase, tipo_licencia, categoria_informe, sit_rev, goce_haberes, autoridad, plazo) VALUES
    ('01.02.01', '309 B-2)', 'Licencia', 'ENFERMEDAD LARGO TRATAMIENTO, LESIÓN GRAVE O MOTIVO DE PROFILAXIS Y SEGURIDAD',
        'Largo tratamiento', 'Titular',  'Con goce de haberes', 'Director', 'Dos (2) años'),
    ('01.02.07', '340 B)',   'Licencia', 'ENFERMEDAD LARGO TRATAMIENTO, LESIÓN GRAVE O MOTIVO DE PROFILAXIS Y SEGURIDAD',
        'Largo tratamiento', 'Suplente', 'Con goce de haberes', 'Director', 'Dos (2) años'),
    ('01.01.04', '340-A',    'Licencia', 'ENFERMEDAD O LESION COMUN',
        'Enfermedad común',  'Suplente', 'Con goce de haberes', 'Director',
        '15 días por año, antig. > 4 meses; 5 días otros casos');
-- Los códigos de PERMISO e INASISTENCIA se cargan igual, con clase = 'Permiso'
-- o 'Inasistencia' (hay que tomarlos de la tabla de códigos oficial).

INSERT INTO designacion
    (dni, cargo_id, espacio_curricular_id, unidad_educativa_id, especialidad_id,
     sit_rev, anio_curso, division_seccion, turno, hs_catedra, jornada,
     motivo_id, motivo_instrumento_legal,
     norma_tipo, norma_nro, norma_anio, org_emisor, desde, hasta, pof, anio_pof)
VALUES
    (10000001, 1, 1,    1, 1,    'Titular', '2do', 'A', 'Noche', 6, 'Simple',
        1, 'Res. 10/2024',
        'Resolución', '123', 2024, 'Ministerio', '2024-03-01', NULL, 'POF-1', 2026),
    (10000003, 2, NULL, 1, NULL, 'Titular', NULL,  NULL, 'Noche', NULL, 'Simple',
        1, 'Res. 11/2023',
        'Resolución', '789', 2023, 'Ministerio', '2023-03-01', NULL, 'POF-3', 2026);

-- La titular (designación 1) presenta una licencia por largo tratamiento
INSERT INTO licencia_otorgada
    (designacion_id, articulo_id, sit_rev, disp_tipo, disp_oficina, disp_numero, disp_anio,
     sello_regional_as, justifica, desde, hasta) VALUES
    (1, 1, 'Titular', 'DISPOSICIÓN', '0001', '321', 2026, 'A.S. 55 A', NULL, '2026-04-01', '2026-04-30');

-- Su suplente se designa con resolución propia, inicio y fin
-- (reemplaza a la designación 1 por la licencia 1: DP-01, "Datos del reemplazado")
INSERT INTO designacion
    (dni, cargo_id, espacio_curricular_id, unidad_educativa_id, especialidad_id,
     suple_licencia_id, reemplazado_designacion_id, sit_rev,
     anio_curso, division_seccion, turno, hs_catedra, jornada,
     disp_alta_nro, sello_regional_as, motivo_id, motivo_instrumento_legal,
     norma_tipo, norma_nro, norma_anio, org_emisor, desde, hasta, pof, anio_pof)
VALUES
    (10000002, 1, 1, 1, 1,
     1, 1, 'Suplente',
     '2do', 'A', 'Noche', 6, 'Simple',
     '77', 'A.S. 55 A', 2, 'Disp. 321/2026',
     'Resolución', '456', 2026, 'Dirección', '2026-04-01', '2026-04-30', 'POF-2', 2026);

INSERT INTO horario (designacion_id, dia, horas_catedra, hora_inicio, hora_fin) VALUES
    (1, 'Lunes',   3, '18:00', '20:15'),
    (1, 'Jueves',  3, '18:00', '20:15'),
    (2, 'Lunes',   6, '18:00', '23:00'),
    (3, 'Lunes',   3, '18:00', '20:15'),
    (3, 'Jueves',  3, '18:00', '20:15');

INSERT INTO asistencia
    (designacion_id, fecha, estado, horas_inasistidas, licencia_otorgada_id, observaciones) VALUES
    (1, '2026-04-06', 'Licencia', 3, 1,    'Licencia por largo tratamiento'),
    (3, '2026-04-06', 'Presente', 0, NULL, NULL),
    (2, '2026-04-06', 'Ausente',  2, NULL, 'Retiro anticipado'),
    (3, '2026-04-09', 'Presente', 0, NULL, NULL);

-- =====================================================================
-- 8. Consultas de ejemplo para los informes
-- =====================================================================

-- 8.1 Quién ejerce qué cargo, en qué materia/carrera y cuándo
--     (los bedeles aparecen sin materia ni carrera)
SELECT p.apellido_nombre,
       cg.descripcion  AS cargo,
       c.nombre        AS carrera,
       e.nombre        AS materia,
       g.sit_rev,
       h.dia,
       h.horas_catedra
FROM designacion g
JOIN personal p                 ON p.dni  = g.dni
JOIN cargo cg                   ON cg.id  = g.cargo_id
LEFT JOIN espacio_curricular e  ON e.id   = g.espacio_curricular_id
LEFT JOIN carrera c             ON c.id   = e.carrera_id
LEFT JOIN horario h             ON h.designacion_id = g.id
ORDER BY p.apellido_nombre, h.dia;

-- 8.2 Informe de asistencia DIARIA por materia (docentes y no docentes)
SELECT a.fecha,
       p.apellido_nombre,
       cg.descripcion               AS cargo,
       COALESCE(e.nombre, '(sin materia)') AS materia,
       a.estado,
       a.horas_inasistidas
FROM asistencia a
JOIN designacion g              ON g.id   = a.designacion_id
JOIN personal p                 ON p.dni  = g.dni
JOIN cargo cg                   ON cg.id  = g.cargo_id
LEFT JOIN espacio_curricular e  ON e.id   = g.espacio_curricular_id
WHERE a.fecha = '2026-04-06'
ORDER BY materia, p.apellido_nombre;

-- 8.3 Informe de asistencia MENSUAL por materia (docentes y no docentes)
SELECT YEAR(a.fecha)  AS anio,
       MONTH(a.fecha) AS mes,
       IF(cg.es_docente, 'Docente', 'No docente') AS tipo_personal,
       COALESCE(e.nombre, '(sin materia)')        AS materia,
       p.apellido_nombre,
       SUM(a.estado = 'Presente')                 AS dias_presente,
       SUM(a.estado = 'Ausente')                  AS dias_ausente,
       SUM(a.estado = 'Licencia')                 AS dias_licencia,
       SUM(a.horas_inasistidas)                   AS horas_inasistidas
FROM asistencia a
JOIN designacion g              ON g.id   = a.designacion_id
JOIN personal p                 ON p.dni  = g.dni
JOIN cargo cg                   ON cg.id  = g.cargo_id
LEFT JOIN espacio_curricular e  ON e.id   = g.espacio_curricular_id
WHERE a.fecha >= '2026-04-01' AND a.fecha < '2026-05-01'
GROUP BY anio, mes, tipo_personal, materia, p.apellido_nombre
ORDER BY tipo_personal, materia, p.apellido_nombre;

-- 8.4 Informe MENSUAL de licencias por enfermedad, por cargo
--     (categorías del informe: enfermedad común y largo tratamiento)
SELECT cg.cod,
       cg.descripcion               AS cargo,
       la.categoria_informe,
       COUNT(DISTINCT lo.id)        AS licencias,
       COUNT(a.id)                  AS dias_con_licencia,
       COALESCE(SUM(a.horas_inasistidas), 0) AS horas_inasistidas
FROM licencia_otorgada lo
JOIN licencia_articulo la ON la.id = lo.articulo_id
JOIN designacion g        ON g.id  = lo.designacion_id
JOIN cargo cg             ON cg.id = g.cargo_id
LEFT JOIN asistencia a    ON a.licencia_otorgada_id = lo.id
                         AND a.fecha >= '2026-04-01' AND a.fecha < '2026-05-01'
WHERE la.categoria_informe IN ('Enfermedad común', 'Largo tratamiento')
  AND lo.desde < '2026-05-01'
  AND COALESCE(lo.hasta, '9999-12-31') >= '2026-04-01'
GROUP BY cg.id, cg.cod, cg.descripcion, la.categoria_informe
ORDER BY cg.cod, la.categoria_informe;

-- 8.5 Formulario Nº 1: datos del agente + trámite de ingreso
SELECT p.apellido, p.nombres, p.dni, p.tipo_documento, p.sexo,
       DAY(p.fecha_nacimiento)   AS dia,
       MONTH(p.fecha_nacimiento) AS mes,
       YEAR(p.fecha_nacimiento)  AS anio,
       p.estado_civil, p.nacionalidad, p.nro_dgi, p.nro_dgr,
       p.domicilio_calle, p.barrio, p.localidad, p.codigo_postal,
       p.provincia, p.telefono,
       i.documentacion_adjunta, i.lugar_presentacion, i.fecha_presentacion,
       i.lugar_recepcion, i.fecha_recepcion,
       i.jurisdiccion, i.escalafon, i.item_nivel, i.modalidad, i.oficina,
       i.sagp_fecha_ingreso_bd, i.sagp_cargo,
       i.dgp_fecha_recibido, i.dgp_recibio
FROM personal p
LEFT JOIN ingreso_agente i ON i.dni = p.dni
WHERE p.dni = 10000001;

-- 8.6 Formulario DP-01: disposición de alta (con datos del reemplazado si es suplente)
SELECT g.sit_rev                     AS tipo,          -- Interino / Suplente / Titular
       g.disp_alta_nro, g.sello_regional_as,
       g.desde AS alta_desde, g.hasta AS alta_hasta,
       p.apellido, p.nombres, p.dni, p.sexo,
       u.codigo_oficina, u.codigo_anexo,
       u.numero AS unidad_numero, u.descripcion AS unidad_descripcion,
       u.nivel_modalidad, u.categoria, u.zona, g.jornada, u.localidad_paraje,
       cg.cod AS cod_cargo, cg.descripcion AS cargo,
       g.anio_curso, g.division_seccion, g.turno, g.hs_catedra,
       es.titulo AS especialidad, ca.plan_estudio, e.nombre AS asignatura,
       m.codigo AS cod_motivo, m.descripcion AS motivo, g.motivo_instrumento_legal,
       rp.dni AS reemplazado_dni, rp.sexo AS reemplazado_sexo,
       rp.apellido AS reemplazado_apellido, rp.nombres AS reemplazado_nombres
FROM designacion g
JOIN personal p                 ON p.dni = g.dni
JOIN unidad_educativa u         ON u.id  = g.unidad_educativa_id
JOIN cargo cg                   ON cg.id = g.cargo_id
LEFT JOIN especialidad es       ON es.id = g.especialidad_id
LEFT JOIN espacio_curricular e  ON e.id  = g.espacio_curricular_id
LEFT JOIN carrera ca            ON ca.id = e.carrera_id
LEFT JOIN motivo m              ON m.id  = g.motivo_id
LEFT JOIN designacion gr        ON gr.id = g.reemplazado_designacion_id
LEFT JOIN personal rp           ON rp.dni = gr.dni
WHERE g.sit_rev IN ('Interino', 'Suplente')
ORDER BY g.desde;

-- 8.7 Formulario DL-01: disposición de licencia / permiso / inasistencia
SELECT lo.disp_numero, lo.disp_anio, lo.sello_regional_as,
       p.apellido, p.nombres, p.dni, p.sexo,
       u.codigo_oficina, u.codigo_anexo,
       u.numero AS unidad_numero, u.descripcion AS unidad_descripcion,
       u.nivel_modalidad,
       cg.cod AS cod_cargo, cg.descripcion AS cargo,
       g.anio_curso, g.division_seccion, g.turno, g.hs_catedra,
       e.nombre AS asignatura,
       g.sit_rev,                                  -- Titular / Interino / Suplente
       la.clase,                                   -- Licencia / Permiso / Inasistencia
       la.cod_licencia, la.articulo, la.tipo_licencia AS descripcion,
       lo.justifica,
       la.goce_haberes AS forma_de_pago,
       lo.desde, lo.hasta
FROM licencia_otorgada lo
JOIN licencia_articulo la       ON la.id = lo.articulo_id
JOIN designacion g              ON g.id  = lo.designacion_id
JOIN personal p                 ON p.dni = g.dni
JOIN unidad_educativa u         ON u.id  = g.unidad_educativa_id
JOIN cargo cg                   ON cg.id = g.cargo_id
LEFT JOIN espacio_curricular e  ON e.id  = g.espacio_curricular_id
ORDER BY lo.disp_anio, lo.disp_numero, lo.id;
