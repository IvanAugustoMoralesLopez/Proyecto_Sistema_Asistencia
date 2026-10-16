-- =====================================================================
--  Base de datos: planilla_personal
--  Modelo a partir de la planilla estadística del personal 2026
--  (nivel superior): docentes y personal no docente (p. ej. bedeles),
--  con licencias por artículo y asistencia diaria / mensual.
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

-- PERSONAL: la persona, sea docente o no docente
-- (columnas D.N.I, DOCENTE, SEXO de la planilla)
CREATE TABLE personal (
    dni              INT UNSIGNED  NOT NULL,
    apellido_nombre  VARCHAR(120)  NOT NULL,
    sexo             CHAR(1)       NULL,
    PRIMARY KEY (dni),
    CONSTRAINT chk_personal_sexo CHECK (sexo IN ('F', 'M', 'X'))
) ENGINE=InnoDB;

-- CARGO: catálogo de códigos de cargo (columnas COD y DESCRIPCION)
-- Ej.: 166 = docente suplente, 155 = bedel
-- es_docente = TRUE  -> el cargo se ejerce sobre un espacio curricular
-- es_docente = FALSE -> cargo no docente (bedel, etc.), sin espacio curricular
CREATE TABLE cargo (
    cod          VARCHAR(10)   NOT NULL,
    descripcion  VARCHAR(120)  NOT NULL,
    es_docente   BOOLEAN       NOT NULL DEFAULT TRUE,
    PRIMARY KEY (cod)
) ENGINE=InnoDB;

-- CARRERA: carrera con su plan de estudio
CREATE TABLE carrera (
    id            INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    nombre        VARCHAR(120)  NOT NULL,
    plan_estudio  VARCHAR(60)   NOT NULL,
    anio_plan     SMALLINT      NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_carrera (nombre, plan_estudio, anio_plan)
) ENGINE=InnoDB;

-- ESPACIO_CURRICULAR: cada materia pertenece a una carrera (1:N)
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

-- ---------------------------------------------------------------------
-- 3. Catálogo de códigos y artículos de licencia (2.ª hoja de la planilla)
--    Cada artículo aplica a una situación de revista (Titular / Interino /
--    Suplente), por eso sit_rev forma parte de la clave única.
-- ---------------------------------------------------------------------
CREATE TABLE licencia_articulo (
    id             INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    articulo       VARCHAR(20)   NOT NULL,   -- código / n.º de artículo
    tipo_licencia  VARCHAR(80)   NOT NULL,
    sit_rev        VARCHAR(20)   NOT NULL,   -- Titular / Interino / Suplente
    goce_haberes   VARCHAR(30)   NOT NULL,   -- Con goce de haberes / Con 50% de haberes
    autoridad      VARCHAR(20)   NOT NULL,   -- Director / Ministro
    plazo          VARCHAR(120)  NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_articulo_sit (articulo, sit_rev),
    UNIQUE KEY uq_articulo_id_sit (id, sit_rev),
    CONSTRAINT chk_articulo_sit_rev
        CHECK (sit_rev IN ('Titular', 'Interino', 'Suplente'))
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 4. Tabla intermedia: DESIGNACION (personal <-> cargo <-> espacio curricular)
--    Cada fila = un cargo que ejerce una persona.
--    - Docentes: espacio_curricular_id completo.
--    - Bedeles y otro personal no docente: espacio_curricular_id NULL.
--    - Suplentes: suple_licencia_id apunta a la licencia que cubren;
--      sus norma_* / desde / hasta son la resolución del suplente
--      y el inicio y fin de la suplencia.
--    Regla a validar en la aplicación: si cargo.es_docente = TRUE,
--    espacio_curricular_id no debería ser NULL.
-- ---------------------------------------------------------------------
CREATE TABLE designacion (
    id                     INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    dni                    INT UNSIGNED  NOT NULL,
    cod                    VARCHAR(10)   NOT NULL,   -- COD (código del cargo)
    espacio_curricular_id  INT UNSIGNED  NULL,       -- solo cargos docentes
    suple_licencia_id      INT UNSIGNED  NULL,       -- licencia que cubre (solo suplentes)
    sit_rev                VARCHAR(20)   NOT NULL,   -- SIT.REV.
    norma_tipo             VARCHAR(30)   NULL,       -- Tipo (resolución, etc.)
    norma_nro              VARCHAR(20)   NULL,       -- Nº
    norma_anio             SMALLINT      NULL,       -- Año
    org_emisor             VARCHAR(60)   NULL,       -- Org. Emisor
    desde                  DATE          NOT NULL,
    hasta                  DATE          NULL,
    pof                    VARCHAR(30)   NULL,
    anio_pof               SMALLINT      NULL,
    observaciones          TEXT          NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_designacion (dni, cod, espacio_curricular_id, desde),
    UNIQUE KEY uq_designacion_id_sit (id, sit_rev),
    CONSTRAINT chk_designacion_sit_rev
        CHECK (sit_rev IN ('Titular', 'Interino', 'Suplente')),
    CONSTRAINT chk_designacion_fechas
        CHECK (hasta IS NULL OR hasta >= desde),
    CONSTRAINT fk_designacion_personal
        FOREIGN KEY (dni) REFERENCES personal (dni)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_designacion_cargo
        FOREIGN KEY (cod) REFERENCES cargo (cod)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_designacion_espacio
        FOREIGN KEY (espacio_curricular_id) REFERENCES espacio_curricular (id)
        ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB;

-- LICENCIA_OTORGADA: cada vez que una persona (p. ej. un titular) presenta
-- una licencia. Guarda el artículo, la disposición y el inicio y fin.
-- sit_rev se repite a propósito: las claves compuestas obligan a que el
-- artículo elegido corresponda a la situación de revista del cargo.
CREATE TABLE licencia_otorgada (
    id              INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    designacion_id  INT UNSIGNED  NOT NULL,   -- cargo de quien se ausenta
    articulo_id     INT UNSIGNED  NOT NULL,
    sit_rev         VARCHAR(20)   NOT NULL,
    disp_numero     VARCHAR(20)   NULL,       -- DISP DE LICENCIA
    disp_anio       SMALLINT      NULL,
    desde           DATE          NOT NULL,
    hasta           DATE          NULL,
    observaciones   TEXT          NULL,
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
    horas_catedra   TINYINT UNSIGNED NOT NULL,
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

-- ---------------------------------------------------------------------
-- 6. Especialidades (opcional: la planilla no trae estos datos)
--    Relación N:M entre personal y especialidad
-- ---------------------------------------------------------------------
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

-- =====================================================================
-- 7. Datos de prueba FICTICIOS (podés borrar esta sección)
--    Los códigos 166 y 155 siguen la planilla; el resto es inventado.
-- =====================================================================
INSERT INTO personal (dni, apellido_nombre, sexo) VALUES
    (10000001, 'Pérez, Ana',     'F'),
    (10000002, 'Gómez, Carlos',  'M'),
    (10000003, 'López, María',   'F');

INSERT INTO cargo (cod, descripcion, es_docente) VALUES
    ('101', 'Docente titular',  TRUE),
    ('166', 'Docente suplente', TRUE),
    ('155', 'Bedel',            FALSE);

INSERT INTO carrera (nombre, plan_estudio, anio_plan) VALUES
    ('Tecnicatura en Desarrollo de Software', 'Plan 2020', 2020),
    ('Tecnicatura en Redes',                  'Plan 2019', 2019);

INSERT INTO espacio_curricular (nombre, carrera_id) VALUES
    ('Programación III',      1),
    ('Base de Datos',         1),
    ('Redes de Computadoras', 2);

INSERT INTO licencia_articulo
    (articulo, tipo_licencia, sit_rev, goce_haberes, autoridad, plazo) VALUES
    ('Art. 10', 'Enfermedad o lesión común', 'Titular',  'Con goce de haberes', 'Director', '15 días por año'),
    ('Art. 10', 'Enfermedad o lesión común', 'Suplente', 'Con goce de haberes', 'Director', '5 días por año');

INSERT INTO designacion
    (dni, cod, espacio_curricular_id, sit_rev,
     norma_tipo, norma_nro, norma_anio, org_emisor, desde, hasta, pof, anio_pof)
VALUES
    (10000001, '101', 1,    'Titular',  'Resolución', '123', 2024, 'Ministerio', '2024-03-01', NULL,         'POF-1', 2026),
    (10000003, '155', NULL, 'Titular',  'Resolución', '789', 2023, 'Ministerio', '2023-03-01', NULL,         'POF-3', 2026);

-- La titular (designación 1) presenta una licencia por enfermedad
INSERT INTO licencia_otorgada
    (designacion_id, articulo_id, sit_rev, disp_numero, disp_anio, desde, hasta) VALUES
    (1, 1, 'Titular', '321', 2026, '2026-04-01', '2026-04-30');

-- Su suplente se designa con resolución propia, inicio y fin
INSERT INTO designacion
    (dni, cod, espacio_curricular_id, suple_licencia_id, sit_rev,
     norma_tipo, norma_nro, norma_anio, org_emisor, desde, hasta, pof, anio_pof)
VALUES
    (10000002, '166', 1, 1, 'Suplente', 'Resolución', '456', 2026, 'Dirección', '2026-04-01', '2026-04-30', 'POF-2', 2026);

INSERT INTO horario (designacion_id, dia, horas_catedra, hora_inicio, hora_fin) VALUES
    (1, 'Lunes',   3, '18:00', '20:15'),
    (1, 'Jueves',  3, '18:00', '20:15'),
    (2, 'Lunes',   6, '18:00', '23:00'),
    (3, 'Lunes',   3, '18:00', '20:15'),
    (3, 'Jueves',  3, '18:00', '20:15');

INSERT INTO asistencia
    (designacion_id, fecha, estado, horas_inasistidas, licencia_otorgada_id, observaciones) VALUES
    (1, '2026-04-06', 'Licencia', 3, 1,    'Licencia por enfermedad'),
    (3, '2026-04-06', 'Presente', 0, NULL, NULL),
    (2, '2026-04-06', 'Ausente',  2, NULL, 'Retiro anticipado'),
    (3, '2026-04-09', 'Presente', 0, NULL, NULL);

INSERT INTO especialidad (titulo) VALUES
    ('Analista de Sistemas'),
    ('Técnico en Redes');

INSERT INTO personal_especialidad (dni, especialidad_id) VALUES
    (10000001, 1),
    (10000002, 1),
    (10000002, 2);

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
JOIN cargo cg                   ON cg.cod = g.cod
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
JOIN cargo cg                   ON cg.cod = g.cod
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
JOIN cargo cg                   ON cg.cod = g.cod
LEFT JOIN espacio_curricular e  ON e.id   = g.espacio_curricular_id
WHERE a.fecha >= '2026-04-01' AND a.fecha < '2026-05-01'
GROUP BY anio, mes, tipo_personal, materia, p.apellido_nombre
ORDER BY tipo_personal, materia, p.apellido_nombre;

-- 8.4 Informe MENSUAL de licencias por enfermedad, por cargo
SELECT cg.cod,
       cg.descripcion               AS cargo,
       COUNT(DISTINCT lo.id)        AS licencias,
       COUNT(a.id)                  AS dias_con_licencia,
       COALESCE(SUM(a.horas_inasistidas), 0) AS horas_inasistidas
FROM licencia_otorgada lo
JOIN licencia_articulo la ON la.id = lo.articulo_id
JOIN designacion g        ON g.id  = lo.designacion_id
JOIN cargo cg             ON cg.cod = g.cod
LEFT JOIN asistencia a    ON a.licencia_otorgada_id = lo.id
                         AND a.fecha >= '2026-04-01' AND a.fecha < '2026-05-01'
WHERE la.tipo_licencia LIKE 'Enfermedad%'
  AND lo.desde < '2026-05-01'
  AND COALESCE(lo.hasta, '9999-12-31') >= '2026-04-01'
GROUP BY cg.cod, cg.descripcion
ORDER BY cg.cod;
