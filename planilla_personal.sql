-- =============================================================================
-- planilla_personal — versión consolidada v4
-- Sistema de registro de asistencia, legajo y licencias del personal del IESETyFP
-- (Oficina 1452). Reúne la v3, los cambios de la revisión y las reglas del ERS v2.0.
--
-- Motor: MySQL 8.0.16+ o MariaDB 10.2+ (usa CHECK, JSON, triggers y procedimientos).
-- Charset utf8mb4. Crea todo desde cero.
--
-- ÍNDICE
--   1. Seguridad: rol, permiso, rol_permiso, usuario
--   2. Catálogos y configuración
--   3. Legajo del personal: personal, designacion, horario
--   4. Licencias y asistencia: disposicion, licencia_otorgada, asistencia
--   5. Control: cierre_periodo, importacion_log, auditoria
--   6. Funciones y reglas de negocio (RN-06, RN-09, RN-10, sin superposición)
--   7. Auditoría automática por triggers (RF-20)
--   8. Vistas: v_inasistencia_mensual, v_licencia_acumulada, v_alerta_topes
--   9. Procedimientos: sp_propagar_licencia, sp_asignar_disposiciones
--  10. Datos iniciales
--
-- CÓMO LO USA LA APLICACIÓN
--   * Al abrir cada conexión: SET @usuario_id = <id del usuario>;  (para la auditoría)
--   * Cargar una licencia: INSERT en licencia_otorgada y luego CALL sp_propagar_licencia(id);
--   * Cerrar un día: INSERT en cierre_periodo (tipo 'DIA'). Para corregir, pasar a 'REABIERTO'.
--   * Fin de mes: CALL sp_asignar_disposiciones(2026, 10, '1452');
-- =============================================================================
CREATE DATABASE IF NOT EXISTS planilla_personal
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE planilla_personal;

-- =============================================================================
-- 1. SEGURIDAD: roles, permisos y usuarios (RF-19)
-- =============================================================================
CREATE TABLE rol (
  id      INT AUTO_INCREMENT PRIMARY KEY,
  codigo  VARCHAR(20) NOT NULL UNIQUE,
  nombre  VARCHAR(60) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE permiso (
  codigo       VARCHAR(40)  NOT NULL PRIMARY KEY,
  descripcion  VARCHAR(160) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE rol_permiso (
  rol_id          INT         NOT NULL,
  permiso_codigo  VARCHAR(40) NOT NULL,
  PRIMARY KEY (rol_id, permiso_codigo),
  CONSTRAINT fk_rp_rol     FOREIGN KEY (rol_id) REFERENCES rol(id),
  CONSTRAINT fk_rp_permiso FOREIGN KEY (permiso_codigo) REFERENCES permiso(codigo)
) ENGINE=InnoDB;

CREATE TABLE usuario (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  rol_id         INT NOT NULL,
  username       VARCHAR(40)  NOT NULL UNIQUE,
  password_hash  VARCHAR(255) NOT NULL,          -- hash generado por la aplicación
  apellido       VARCHAR(80)  NOT NULL,
  nombres        VARCHAR(80)  NOT NULL,
  email          VARCHAR(120),
  activo         BOOLEAN NOT NULL DEFAULT TRUE,
  ultimo_acceso  DATETIME NULL,
  CONSTRAINT fk_usuario_rol FOREIGN KEY (rol_id) REFERENCES rol(id)
) ENGINE=InnoDB;

-- =============================================================================
-- 2. CATÁLOGOS (RF-05) y CONFIGURACIÓN (RF-10, RF-21)
-- =============================================================================
CREATE TABLE situacion_revista (
  codigo       VARCHAR(20) NOT NULL PRIMARY KEY,
  descripcion  VARCHAR(80) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE unidad_educativa (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  numero            VARCHAR(20),
  descripcion       VARCHAR(120),
  codigo_oficina    VARCHAR(10),
  codigo_anexo      VARCHAR(10),
  nivel_modalidad   VARCHAR(60),
  categoria         VARCHAR(20),
  zona              VARCHAR(30),
  localidad_paraje  VARCHAR(80)
) ENGINE=InnoDB;

CREATE TABLE cargo (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  cod         VARCHAR(10)  NOT NULL UNIQUE,
  descripcion VARCHAR(120) NOT NULL,
  es_docente  BOOLEAN NOT NULL DEFAULT TRUE
) ENGINE=InnoDB;

CREATE TABLE motivo (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  codigo      CHAR(5)      NOT NULL UNIQUE,
  descripcion VARCHAR(200) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE carrera (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  nombre        VARCHAR(120) NOT NULL,
  plan_estudio  VARCHAR(60),
  anio_plan     SMALLINT
) ENGINE=InnoDB;

CREATE TABLE espacio_curricular (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  nombre      VARCHAR(120) NOT NULL,
  carrera_id  INT NOT NULL,
  UNIQUE KEY uq_espacio_carrera (carrera_id, nombre),
  CONSTRAINT fk_espacio_carrera FOREIGN KEY (carrera_id) REFERENCES carrera(id)
) ENGINE=InnoDB;

CREATE TABLE especialidad (
  id      INT AUTO_INCREMENT PRIMARY KEY,
  titulo  VARCHAR(120) NOT NULL
) ENGINE=InnoDB;

-- Catálogo de licencias por artículo. Los topes están en campos numéricos (RF-18, RN-08);
-- "plazo" conserva el texto original del catálogo como referencia.
CREATE TABLE licencia_articulo (
  id                       INT AUTO_INCREMENT PRIMARY KEY,
  cod_licencia             VARCHAR(12) NOT NULL,
  articulo                 VARCHAR(20),
  clase                    ENUM('SALUD','ADMINISTRATIVA') NOT NULL,
  tipo_licencia            VARCHAR(120),
  categoria_informe        ENUM('IL-01','IL-02') NOT NULL,      -- RN-04 / RN-05
  es_largo_tratamiento     BOOLEAN NOT NULL DEFAULT FALSE,      -- marca LT en la asistencia
  sit_rev                  VARCHAR(20),
  goce_haberes             VARCHAR(30),
  autoridad                VARCHAR(30),
  plazo                    VARCHAR(200),
  tope_cantidad            INT UNSIGNED NULL,
  tope_unidad              ENUM('DIAS','ANIOS') NULL,
  tope_periodo             ENUM('POR_VEZ','POR_ANIO','POR_DECENIO') NULL,
  tope_dias_corridos       BOOLEAN NULL,
  antiguedad_min_meses     SMALLINT UNSIGNED NULL,
  tope_cantidad_sin_antig  INT UNSIGNED NULL,
  activo                   BOOLEAN NOT NULL DEFAULT TRUE,
  KEY idx_licart_cod (cod_licencia)
) ENGINE=InnoDB;

CREATE TABLE calendario_escolar (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  fecha          DATE NOT NULL UNIQUE,
  tipo           ENUM('FERIADO','ASUETO','INHABIL','INSTITUCIONAL') NOT NULL,
  descripcion    VARCHAR(120) NOT NULL,
  ciclo_lectivo  SMALLINT NOT NULL
) ENGINE=InnoDB;

CREATE TABLE parametro (
  clave        VARCHAR(40)  NOT NULL PRIMARY KEY,
  valor        VARCHAR(200) NOT NULL,
  descripcion  VARCHAR(200) NULL
) ENGINE=InnoDB;

-- =============================================================================
-- 3. LEGAJO DEL PERSONAL (RF-01 a RF-04)
-- =============================================================================
CREATE TABLE personal (
  dni               VARCHAR(10) NOT NULL PRIMARY KEY,           -- RF-01: DNI en formato texto
  tipo_documento    VARCHAR(10) NOT NULL DEFAULT 'DNI',
  apellido          VARCHAR(80) NOT NULL,
  nombres           VARCHAR(80) NOT NULL,
  apellido_nombre   VARCHAR(165) GENERATED ALWAYS AS (CONCAT(apellido, ', ', nombres)) STORED,
  sexo              CHAR(1),
  fecha_nacimiento  DATE,
  estado_civil      VARCHAR(20),
  nacionalidad      VARCHAR(40),
  nro_dgi           VARCHAR(20),
  nro_dgr           VARCHAR(20),
  domicilio_calle   VARCHAR(120),
  barrio            VARCHAR(80),
  localidad         VARCHAR(80),
  codigo_postal     VARCHAR(10),
  provincia         VARCHAR(60),
  telefono          VARCHAR(30),
  email             VARCHAR(120),
  KEY idx_personal_apellido (apellido, nombres)
) ENGINE=InnoDB;

CREATE TABLE personal_especialidad (
  dni              VARCHAR(10) NOT NULL,
  especialidad_id  INT NOT NULL,
  PRIMARY KEY (dni, especialidad_id),
  CONSTRAINT fk_pe_personal     FOREIGN KEY (dni) REFERENCES personal(dni) ON UPDATE CASCADE,
  CONSTRAINT fk_pe_especialidad FOREIGN KEY (especialidad_id) REFERENCES especialidad(id)
) ENGINE=InnoDB;

CREATE TABLE ingreso_agente (
  id                     INT AUTO_INCREMENT PRIMARY KEY,
  dni                    VARCHAR(10) NOT NULL,
  documentacion_adjunta  VARCHAR(255),
  lugar_presentacion     VARCHAR(80),
  fecha_presentacion     DATE,
  lugar_recepcion        VARCHAR(80),
  fecha_recepcion        DATE,
  responsable_recepcion  VARCHAR(120),
  jurisdiccion           VARCHAR(40),
  escalafon              VARCHAR(40),
  item_nivel             VARCHAR(40),
  modalidad              VARCHAR(40),
  oficina                VARCHAR(40),
  sagp_fecha_ingreso_bd  DATE,
  sagp_cargo             VARCHAR(80),
  dgp_fecha_recibido     DATE,
  dgp_recibio            VARCHAR(120),
  CONSTRAINT fk_ingreso_personal FOREIGN KEY (dni) REFERENCES personal(dni) ON UPDATE CASCADE
) ENGINE=InnoDB;

-- desde NULL = "SIN INICIO"; hasta NULL = "SIN TERMINO" (la aplicación muestra esos textos).
CREATE TABLE designacion (
  id                          INT AUTO_INCREMENT PRIMARY KEY,
  dni                         VARCHAR(10) NOT NULL,
  cargo_id                    INT NOT NULL,
  espacio_curricular_id       INT NULL,
  unidad_educativa_id         INT NOT NULL,
  especialidad_id             INT NULL,
  suple_licencia_id           INT NULL,        -- FK a licencia_otorgada (se agrega más abajo)
  reemplazado_designacion_id  INT NULL,
  sit_rev                     VARCHAR(20) NULL,
  anio_curso                  VARCHAR(10),
  division_seccion            VARCHAR(20),
  turno                       VARCHAR(20),
  hs_catedra                  TINYINT UNSIGNED,
  jornada                     VARCHAR(30),
  disp_alta_nro               VARCHAR(20),
  sello_regional_as           VARCHAR(30),
  motivo_id                   INT NULL,
  motivo_instrumento_legal    VARCHAR(40),
  norma_tipo                  VARCHAR(30),
  norma_nro                   VARCHAR(20),
  norma_anio                  SMALLINT,
  org_emisor                  VARCHAR(60),
  desde                       DATE NULL,
  hasta                       DATE NULL,
  pof                         VARCHAR(30),
  anio_pof                    SMALLINT,
  novedad                     VARCHAR(40),
  observaciones               TEXT,
  KEY idx_desig_dni (dni),
  KEY idx_desig_vigencia (desde, hasta),
  CONSTRAINT fk_desig_personal  FOREIGN KEY (dni) REFERENCES personal(dni) ON UPDATE CASCADE,
  CONSTRAINT fk_desig_cargo     FOREIGN KEY (cargo_id) REFERENCES cargo(id),
  CONSTRAINT fk_desig_espacio   FOREIGN KEY (espacio_curricular_id) REFERENCES espacio_curricular(id),
  CONSTRAINT fk_desig_unidad    FOREIGN KEY (unidad_educativa_id) REFERENCES unidad_educativa(id),
  CONSTRAINT fk_desig_espec     FOREIGN KEY (especialidad_id) REFERENCES especialidad(id),
  CONSTRAINT fk_desig_reemplaza FOREIGN KEY (reemplazado_designacion_id) REFERENCES designacion(id),
  CONSTRAINT fk_desig_motivo    FOREIGN KEY (motivo_id) REFERENCES motivo(id),
  CONSTRAINT fk_desig_sitrev    FOREIGN KEY (sit_rev) REFERENCES situacion_revista(codigo) ON UPDATE CASCADE,
  CONSTRAINT ck_desig_fechas    CHECK (desde IS NULL OR hasta IS NULL OR hasta >= desde)
) ENGINE=InnoDB;

-- Horario semanal de cada designación. El personal no docente (ej. bedel) se carga con
-- horas_catedra = 0 y hora_inicio / hora_fin: así también se le genera la asistencia diaria.
CREATE TABLE horario (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  designacion_id  INT NOT NULL,
  dia             ENUM('LUN','MAR','MIE','JUE','VIE') NOT NULL,
  horas_catedra   TINYINT UNSIGNED NOT NULL,
  hora_inicio     TIME,
  hora_fin        TIME,
  KEY idx_horario_desig (designacion_id, dia),
  CONSTRAINT fk_horario_desig FOREIGN KEY (designacion_id) REFERENCES designacion(id),
  CONSTRAINT ck_horario_horas CHECK (hora_inicio IS NULL OR hora_fin IS NULL OR hora_fin > hora_inicio)
) ENGINE=InnoDB;

-- =============================================================================
-- 4. LICENCIAS Y ASISTENCIA (RF-07 a RF-16)
-- =============================================================================
-- Disposición interna (numeración correlativa) o resolución externa. Una disposición
-- puede amparar varias licencias.
CREATE TABLE disposicion (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  tipo              ENUM('INTERNA','EXTERNA') NOT NULL,
  dni_beneficiario  VARCHAR(10) NULL,
  oficina_codigo    VARCHAR(10) NOT NULL,
  anio              SMALLINT NOT NULL,
  numero            INT UNSIGNED NOT NULL,
  org_emisor        VARCHAR(60) NULL,
  fecha_emision     DATE NULL,
  periodo_mes       TINYINT UNSIGNED NULL,
  anulada           BOOLEAN NOT NULL DEFAULT FALSE,
  observaciones     TEXT NULL,
  UNIQUE KEY uq_disposicion (tipo, oficina_codigo, anio, numero),
  CONSTRAINT fk_disp_personal FOREIGN KEY (dni_beneficiario) REFERENCES personal(dni) ON UPDATE CASCADE,
  CONSTRAINT ck_disp_mes      CHECK (periodo_mes IS NULL OR periodo_mes BETWEEN 1 AND 12)
) ENGINE=InnoDB;

-- sit_rev es una foto de la situación de revista al momento de la licencia: no tiene FK
-- (así se puede cambiar la situación de revista de la designación sin trabas).
CREATE TABLE licencia_otorgada (
  id                          INT AUTO_INCREMENT PRIMARY KEY,
  designacion_id              INT NOT NULL,
  articulo_id                 INT NOT NULL,
  sit_rev                     VARCHAR(20),
  disposicion_interna_id      INT NULL,
  resolucion_externa_id       INT NULL,
  nro_formulario_papel        VARCHAR(20) NULL,
  fecha_recepcion_formulario  DATE NULL,
  sello_regional_as           VARCHAR(30),
  justifica                   BOOLEAN NOT NULL DEFAULT FALSE,
  desde                       DATE NOT NULL,
  hasta                       DATE NULL,
  anulada                     BOOLEAN NOT NULL DEFAULT FALSE,
  observaciones               TEXT,
  KEY idx_lic_desig (designacion_id, desde),
  CONSTRAINT fk_lic_desig    FOREIGN KEY (designacion_id) REFERENCES designacion(id),
  CONSTRAINT fk_lic_articulo FOREIGN KEY (articulo_id) REFERENCES licencia_articulo(id),
  CONSTRAINT fk_lic_disp     FOREIGN KEY (disposicion_interna_id) REFERENCES disposicion(id),
  CONSTRAINT fk_lic_res      FOREIGN KEY (resolucion_externa_id) REFERENCES disposicion(id),
  CONSTRAINT ck_lic_fechas   CHECK (hasta IS NULL OR hasta >= desde),
  CONSTRAINT ck_lic_papel    CHECK (disposicion_interna_id IS NULL OR nro_formulario_papel IS NOT NULL)  -- RN-10
) ENGINE=InnoDB;

ALTER TABLE designacion
  ADD CONSTRAINT fk_desig_suple_lic FOREIGN KEY (suple_licencia_id) REFERENCES licencia_otorgada(id);

-- Un registro por designación y día (el docente puede faltar a una materia y dictar otra).
CREATE TABLE asistencia (
  id                    INT AUTO_INCREMENT PRIMARY KEY,
  designacion_id        INT NOT NULL,
  fecha                 DATE NOT NULL,
  estado                ENUM('P','I','LIC','LT','PR') NOT NULL,                       -- RF-08
  horas_inasistidas     TINYINT UNSIGNED NOT NULL DEFAULT 0,                          -- RF-13
  licencia_otorgada_id  INT NULL,
  estado_justificacion  ENUM('INJUSTIFICADA','EN_TRAMITE','JUSTIFICADA') NULL,        -- RF-09
  nro_formulario_papel  VARCHAR(20) NULL,
  observaciones         TEXT,
  UNIQUE KEY uq_asistencia (designacion_id, fecha),
  KEY idx_asist_fecha (fecha),
  KEY idx_asist_lic (licencia_otorgada_id),
  CONSTRAINT fk_asist_desig FOREIGN KEY (designacion_id) REFERENCES designacion(id),
  CONSTRAINT fk_asist_lic   FOREIGN KEY (licencia_otorgada_id) REFERENCES licencia_otorgada(id),
  CONSTRAINT ck_asist_lic   CHECK (estado NOT IN ('LIC','LT') OR licencia_otorgada_id IS NOT NULL),
  CONSTRAINT ck_asist_pres  CHECK (estado <> 'P' OR horas_inasistidas = 0),
  CONSTRAINT ck_asist_just  CHECK (estado_justificacion IS NULL OR estado = 'I')
) ENGINE=InnoDB;

-- =============================================================================
-- 5. CONTROL: cierres, importación y auditoría (RN-06, RF-06, RF-20)
-- =============================================================================
CREATE TABLE cierre_periodo (
  id                 INT AUTO_INCREMENT PRIMARY KEY,
  tipo               ENUM('DIA','MES') NOT NULL,
  periodo            DATE NOT NULL COMMENT 'La fecha (DIA) o el primer día del mes (MES)',
  estado             ENUM('CERRADO','REABIERTO') NOT NULL DEFAULT 'CERRADO',
  cerrado_por        INT NOT NULL,
  cerrado_en         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reabierto_por      INT NULL,
  reabierto_en       DATETIME NULL,
  motivo_reapertura  VARCHAR(255) NULL,
  UNIQUE KEY uq_cierre (tipo, periodo),
  CONSTRAINT fk_cierre_cerro   FOREIGN KEY (cerrado_por)   REFERENCES usuario(id),
  CONSTRAINT fk_cierre_reabrio FOREIGN KEY (reabierto_por) REFERENCES usuario(id)
) ENGINE=InnoDB;

CREATE TABLE importacion_log (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  fecha_hora     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  usuario_id     INT NULL,
  archivo        VARCHAR(120) NOT NULL,
  nro_fila       INT NOT NULL,
  dni_texto      VARCHAR(20) NULL,
  motivo_error   VARCHAR(255) NOT NULL,
  fila_original  TEXT NULL,
  CONSTRAINT fk_implog_usuario FOREIGN KEY (usuario_id) REFERENCES usuario(id)
) ENGINE=InnoDB;

CREATE TABLE auditoria (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  fecha_hora      DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  usuario_id      INT NOT NULL,
  accion          ENUM('ALTA','MODIFICACION','ANULACION','BAJA') NOT NULL,
  tabla           VARCHAR(60) NOT NULL,
  registro_id     VARCHAR(40) NOT NULL,
  dni_afectado    VARCHAR(10) NULL,
  valor_anterior  JSON NULL,
  valor_nuevo     JSON NULL,
  ip              VARCHAR(45) NULL,
  KEY idx_aud_fecha (fecha_hora),
  KEY idx_aud_tabla_reg (tabla, registro_id),
  KEY idx_aud_dni (dni_afectado),
  CONSTRAINT fk_aud_usuario FOREIGN KEY (usuario_id) REFERENCES usuario(id)
) ENGINE=InnoDB;
-- =============================================================================
-- 6. FUNCIONES Y REGLAS DE NEGOCIO (triggers)
-- Requieren MySQL 8.0.16+ / MariaDB 10.2+. Si el servidor tiene el log binario activo y el
-- usuario no es SUPER, hace falta: SET GLOBAL log_bin_trust_function_creators = 1;
-- =============================================================================
DELIMITER $$

-- Usuario que realiza la operación. La aplicación debe ejecutar, al abrir cada conexión
-- o request:  SET @usuario_id = <id del usuario>;   Si no lo hace, se registra a 'sistema'.
CREATE FUNCTION fn_usuario_actual() RETURNS INT
READS SQL DATA
BEGIN
  RETURN COALESCE(@usuario_id, (SELECT id FROM usuario WHERE username = 'sistema'));
END$$

-- 1 si la fecha está en un día o mes cerrado (RN-06). Un período REABIERTO permite editar.
CREATE FUNCTION fn_periodo_cerrado(p_fecha DATE) RETURNS TINYINT(1)
READS SQL DATA
BEGIN
  RETURN EXISTS (SELECT 1 FROM cierre_periodo
                  WHERE estado = 'CERRADO'
                    AND ((tipo = 'DIA' AND periodo = p_fecha)
                      OR (tipo = 'MES' AND periodo = DATE_FORMAT(p_fecha, '%Y-%m-01'))));
END$$

-- 1 si la fecha cae dentro de la vigencia de la designación (RN-09).
CREATE FUNCTION fn_vigente_en(p_designacion INT, p_fecha DATE) RETURNS TINYINT(1)
READS SQL DATA
BEGIN
  DECLARE v_n INT; DECLARE v_desde DATE; DECLARE v_hasta DATE;
  SELECT COUNT(*), MIN(desde), MIN(hasta) INTO v_n, v_desde, v_hasta
    FROM designacion WHERE id = p_designacion;
  IF v_n = 0 THEN RETURN 0; END IF;
  RETURN (v_desde IS NULL OR p_fecha >= v_desde) AND (v_hasta IS NULL OR p_fecha <= v_hasta);
END$$

-- ---------------------------------------------------------------------------
-- Asistencia: vigencia de la designación (RN-09) y cierre de períodos (RN-06)
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_asistencia_bi BEFORE INSERT ON asistencia
FOR EACH ROW
BEGIN
  IF NEW.estado = 'I' AND NEW.estado_justificacion IS NULL THEN
    SET NEW.estado_justificacion = 'INJUSTIFICADA';
  END IF;
  IF NOT fn_vigente_en(NEW.designacion_id, NEW.fecha) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'RN-09: la fecha esta fuera de la vigencia de la designacion';
  END IF;
  IF fn_periodo_cerrado(NEW.fecha) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'RN-06: el dia o el mes esta cerrado; hay que reabrirlo para modificar';
  END IF;
END$$

CREATE TRIGGER trg_asistencia_bu BEFORE UPDATE ON asistencia
FOR EACH ROW
BEGIN
  IF NEW.designacion_id <> OLD.designacion_id OR NEW.fecha <> OLD.fecha THEN
    IF NOT fn_vigente_en(NEW.designacion_id, NEW.fecha) THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'RN-09: la fecha esta fuera de la vigencia de la designacion';
    END IF;
  END IF;
  IF fn_periodo_cerrado(OLD.fecha) OR fn_periodo_cerrado(NEW.fecha) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'RN-06: el dia o el mes esta cerrado; hay que reabrirlo para modificar';
  END IF;
END$$

CREATE TRIGGER trg_asistencia_bd BEFORE DELETE ON asistencia
FOR EACH ROW
BEGIN
  IF fn_periodo_cerrado(OLD.fecha) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'RN-06: el dia o el mes esta cerrado; hay que reabrirlo para modificar';
  END IF;
END$$

-- ---------------------------------------------------------------------------
-- Licencias: vigencia (RN-09), sin superposición y tipo correcto de disposición
-- ---------------------------------------------------------------------------
CREATE PROCEDURE sp_validar_licencia(IN p_id INT, IN p_designacion INT, IN p_desde DATE,
                                     IN p_hasta DATE, IN p_anulada TINYINT,
                                     IN p_interna INT, IN p_externa INT)
BEGIN
  DECLARE v_tipo VARCHAR(10);
  IF NOT fn_vigente_en(p_designacion, p_desde) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'RN-09: la licencia empieza fuera de la vigencia de la designacion';
  END IF;
  IF p_anulada = 0 AND EXISTS (
       SELECT 1 FROM licencia_otorgada
        WHERE designacion_id = p_designacion AND anulada = 0 AND id <> COALESCE(p_id, 0)
          AND desde <= COALESCE(p_hasta, '9999-12-31')
          AND COALESCE(hasta, '9999-12-31') >= p_desde) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La designacion ya tiene una licencia que se superpone con ese periodo';
  END IF;
  IF p_interna IS NOT NULL THEN
    SELECT tipo INTO v_tipo FROM disposicion WHERE id = p_interna;
    IF v_tipo IS NULL OR v_tipo <> 'INTERNA' THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'disposicion_interna_id debe apuntar a una disposicion INTERNA';
    END IF;
  END IF;
  IF p_externa IS NOT NULL THEN
    SELECT tipo INTO v_tipo FROM disposicion WHERE id = p_externa;
    IF v_tipo IS NULL OR v_tipo <> 'EXTERNA' THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'resolucion_externa_id debe apuntar a una resolucion EXTERNA';
    END IF;
  END IF;
END$$

CREATE TRIGGER trg_licencia_bi BEFORE INSERT ON licencia_otorgada
FOR EACH ROW
BEGIN
  CALL sp_validar_licencia(NULL, NEW.designacion_id, NEW.desde, NEW.hasta, NEW.anulada,
                           NEW.disposicion_interna_id, NEW.resolucion_externa_id);
END$$

CREATE TRIGGER trg_licencia_bu BEFORE UPDATE ON licencia_otorgada
FOR EACH ROW
BEGIN
  CALL sp_validar_licencia(NEW.id, NEW.designacion_id, NEW.desde, NEW.hasta, NEW.anulada,
                           NEW.disposicion_interna_id, NEW.resolucion_externa_id);
END$$

-- ---------------------------------------------------------------------------
-- La bitácora es inalterable (RF-20): ni UPDATE ni DELETE.
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_auditoria_no_update BEFORE UPDATE ON auditoria
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'auditoria es inalterable: UPDATE no permitido';
END$$

CREATE TRIGGER trg_auditoria_no_delete BEFORE DELETE ON auditoria
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'auditoria es inalterable: DELETE no permitido';
END$$

DELIMITER ;
-- =============================================================================
-- 7. AUDITORÍA AUTOMÁTICA (RF-20)
-- Cada alta, modificación, anulación y baja de las tablas principales queda en `auditoria`
-- con usuario (@usuario_id), fecha/hora y los valores anterior y nuevo en JSON.
-- Las cargas masivas sin @usuario_id se registran a nombre del usuario 'sistema'.
-- =============================================================================
DELIMITER $$

CREATE TRIGGER trg_aud_personal_ai AFTER INSERT ON personal
FOR EACH ROW
BEGIN
  INSERT INTO auditoria (usuario_id, accion, tabla, registro_id, dni_afectado, valor_anterior, valor_nuevo)
  VALUES (fn_usuario_actual(), 'ALTA', 'personal', NEW.dni, NEW.dni, NULL, JSON_OBJECT('dni', NEW.dni, 'tipo_documento', NEW.tipo_documento, 'apellido', NEW.apellido, 'nombres', NEW.nombres, 'sexo', NEW.sexo, 'fecha_nacimiento', NEW.fecha_nacimiento, 'estado_civil', NEW.estado_civil, 'nacionalidad', NEW.nacionalidad, 'nro_dgi', NEW.nro_dgi, 'nro_dgr', NEW.nro_dgr, 'domicilio_calle', NEW.domicilio_calle, 'barrio', NEW.barrio, 'localidad', NEW.localidad, 'codigo_postal', NEW.codigo_postal, 'provincia', NEW.provincia, 'telefono', NEW.telefono, 'email', NEW.email));
END$$

CREATE TRIGGER trg_aud_personal_au AFTER UPDATE ON personal
FOR EACH ROW
BEGIN
  INSERT INTO auditoria (usuario_id, accion, tabla, registro_id, dni_afectado, valor_anterior, valor_nuevo)
  VALUES (fn_usuario_actual(), 'MODIFICACION', 'personal', NEW.dni, NEW.dni, JSON_OBJECT('dni', OLD.dni, 'tipo_documento', OLD.tipo_documento, 'apellido', OLD.apellido, 'nombres', OLD.nombres, 'sexo', OLD.sexo, 'fecha_nacimiento', OLD.fecha_nacimiento, 'estado_civil', OLD.estado_civil, 'nacionalidad', OLD.nacionalidad, 'nro_dgi', OLD.nro_dgi, 'nro_dgr', OLD.nro_dgr, 'domicilio_calle', OLD.domicilio_calle, 'barrio', OLD.barrio, 'localidad', OLD.localidad, 'codigo_postal', OLD.codigo_postal, 'provincia', OLD.provincia, 'telefono', OLD.telefono, 'email', OLD.email), JSON_OBJECT('dni', NEW.dni, 'tipo_documento', NEW.tipo_documento, 'apellido', NEW.apellido, 'nombres', NEW.nombres, 'sexo', NEW.sexo, 'fecha_nacimiento', NEW.fecha_nacimiento, 'estado_civil', NEW.estado_civil, 'nacionalidad', NEW.nacionalidad, 'nro_dgi', NEW.nro_dgi, 'nro_dgr', NEW.nro_dgr, 'domicilio_calle', NEW.domicilio_calle, 'barrio', NEW.barrio, 'localidad', NEW.localidad, 'codigo_postal', NEW.codigo_postal, 'provincia', NEW.provincia, 'telefono', NEW.telefono, 'email', NEW.email));
END$$

CREATE TRIGGER trg_aud_personal_ad AFTER DELETE ON personal
FOR EACH ROW
BEGIN
  INSERT INTO auditoria (usuario_id, accion, tabla, registro_id, dni_afectado, valor_anterior, valor_nuevo)
  VALUES (fn_usuario_actual(), 'BAJA', 'personal', OLD.dni, OLD.dni, JSON_OBJECT('dni', OLD.dni, 'tipo_documento', OLD.tipo_documento, 'apellido', OLD.apellido, 'nombres', OLD.nombres, 'sexo', OLD.sexo, 'fecha_nacimiento', OLD.fecha_nacimiento, 'estado_civil', OLD.estado_civil, 'nacionalidad', OLD.nacionalidad, 'nro_dgi', OLD.nro_dgi, 'nro_dgr', OLD.nro_dgr, 'domicilio_calle', OLD.domicilio_calle, 'barrio', OLD.barrio, 'localidad', OLD.localidad, 'codigo_postal', OLD.codigo_postal, 'provincia', OLD.provincia, 'telefono', OLD.telefono, 'email', OLD.email), NULL);
END$$

CREATE TRIGGER trg_aud_designacion_ai AFTER INSERT ON designacion
FOR EACH ROW
BEGIN
  INSERT INTO auditoria (usuario_id, accion, tabla, registro_id, dni_afectado, valor_anterior, valor_nuevo)
  VALUES (fn_usuario_actual(), 'ALTA', 'designacion', NEW.id, NEW.dni, NULL, JSON_OBJECT('id', NEW.id, 'dni', NEW.dni, 'cargo_id', NEW.cargo_id, 'espacio_curricular_id', NEW.espacio_curricular_id, 'unidad_educativa_id', NEW.unidad_educativa_id, 'especialidad_id', NEW.especialidad_id, 'suple_licencia_id', NEW.suple_licencia_id, 'reemplazado_designacion_id', NEW.reemplazado_designacion_id, 'sit_rev', NEW.sit_rev, 'anio_curso', NEW.anio_curso, 'division_seccion', NEW.division_seccion, 'turno', NEW.turno, 'hs_catedra', NEW.hs_catedra, 'jornada', NEW.jornada, 'disp_alta_nro', NEW.disp_alta_nro, 'sello_regional_as', NEW.sello_regional_as, 'motivo_id', NEW.motivo_id, 'motivo_instrumento_legal', NEW.motivo_instrumento_legal, 'norma_tipo', NEW.norma_tipo, 'norma_nro', NEW.norma_nro, 'norma_anio', NEW.norma_anio, 'org_emisor', NEW.org_emisor, 'desde', NEW.desde, 'hasta', NEW.hasta, 'pof', NEW.pof, 'anio_pof', NEW.anio_pof, 'novedad', NEW.novedad, 'observaciones', NEW.observaciones));
END$$

CREATE TRIGGER trg_aud_designacion_au AFTER UPDATE ON designacion
FOR EACH ROW
BEGIN
  INSERT INTO auditoria (usuario_id, accion, tabla, registro_id, dni_afectado, valor_anterior, valor_nuevo)
  VALUES (fn_usuario_actual(), 'MODIFICACION', 'designacion', NEW.id, NEW.dni, JSON_OBJECT('id', OLD.id, 'dni', OLD.dni, 'cargo_id', OLD.cargo_id, 'espacio_curricular_id', OLD.espacio_curricular_id, 'unidad_educativa_id', OLD.unidad_educativa_id, 'especialidad_id', OLD.especialidad_id, 'suple_licencia_id', OLD.suple_licencia_id, 'reemplazado_designacion_id', OLD.reemplazado_designacion_id, 'sit_rev', OLD.sit_rev, 'anio_curso', OLD.anio_curso, 'division_seccion', OLD.division_seccion, 'turno', OLD.turno, 'hs_catedra', OLD.hs_catedra, 'jornada', OLD.jornada, 'disp_alta_nro', OLD.disp_alta_nro, 'sello_regional_as', OLD.sello_regional_as, 'motivo_id', OLD.motivo_id, 'motivo_instrumento_legal', OLD.motivo_instrumento_legal, 'norma_tipo', OLD.norma_tipo, 'norma_nro', OLD.norma_nro, 'norma_anio', OLD.norma_anio, 'org_emisor', OLD.org_emisor, 'desde', OLD.desde, 'hasta', OLD.hasta, 'pof', OLD.pof, 'anio_pof', OLD.anio_pof, 'novedad', OLD.novedad, 'observaciones', OLD.observaciones), JSON_OBJECT('id', NEW.id, 'dni', NEW.dni, 'cargo_id', NEW.cargo_id, 'espacio_curricular_id', NEW.espacio_curricular_id, 'unidad_educativa_id', NEW.unidad_educativa_id, 'especialidad_id', NEW.especialidad_id, 'suple_licencia_id', NEW.suple_licencia_id, 'reemplazado_designacion_id', NEW.reemplazado_designacion_id, 'sit_rev', NEW.sit_rev, 'anio_curso', NEW.anio_curso, 'division_seccion', NEW.division_seccion, 'turno', NEW.turno, 'hs_catedra', NEW.hs_catedra, 'jornada', NEW.jornada, 'disp_alta_nro', NEW.disp_alta_nro, 'sello_regional_as', NEW.sello_regional_as, 'motivo_id', NEW.motivo_id, 'motivo_instrumento_legal', NEW.motivo_instrumento_legal, 'norma_tipo', NEW.norma_tipo, 'norma_nro', NEW.norma_nro, 'norma_anio', NEW.norma_anio, 'org_emisor', NEW.org_emisor, 'desde', NEW.desde, 'hasta', NEW.hasta, 'pof', NEW.pof, 'anio_pof', NEW.anio_pof, 'novedad', NEW.novedad, 'observaciones', NEW.observaciones));
END$$

CREATE TRIGGER trg_aud_designacion_ad AFTER DELETE ON designacion
FOR EACH ROW
BEGIN
  INSERT INTO auditoria (usuario_id, accion, tabla, registro_id, dni_afectado, valor_anterior, valor_nuevo)
  VALUES (fn_usuario_actual(), 'BAJA', 'designacion', OLD.id, OLD.dni, JSON_OBJECT('id', OLD.id, 'dni', OLD.dni, 'cargo_id', OLD.cargo_id, 'espacio_curricular_id', OLD.espacio_curricular_id, 'unidad_educativa_id', OLD.unidad_educativa_id, 'especialidad_id', OLD.especialidad_id, 'suple_licencia_id', OLD.suple_licencia_id, 'reemplazado_designacion_id', OLD.reemplazado_designacion_id, 'sit_rev', OLD.sit_rev, 'anio_curso', OLD.anio_curso, 'division_seccion', OLD.division_seccion, 'turno', OLD.turno, 'hs_catedra', OLD.hs_catedra, 'jornada', OLD.jornada, 'disp_alta_nro', OLD.disp_alta_nro, 'sello_regional_as', OLD.sello_regional_as, 'motivo_id', OLD.motivo_id, 'motivo_instrumento_legal', OLD.motivo_instrumento_legal, 'norma_tipo', OLD.norma_tipo, 'norma_nro', OLD.norma_nro, 'norma_anio', OLD.norma_anio, 'org_emisor', OLD.org_emisor, 'desde', OLD.desde, 'hasta', OLD.hasta, 'pof', OLD.pof, 'anio_pof', OLD.anio_pof, 'novedad', OLD.novedad, 'observaciones', OLD.observaciones), NULL);
END$$

CREATE TRIGGER trg_aud_licencia_otorgada_ai AFTER INSERT ON licencia_otorgada
FOR EACH ROW
BEGIN
  INSERT INTO auditoria (usuario_id, accion, tabla, registro_id, dni_afectado, valor_anterior, valor_nuevo)
  VALUES (fn_usuario_actual(), 'ALTA', 'licencia_otorgada', NEW.id, (SELECT dni FROM designacion WHERE id = NEW.designacion_id), NULL, JSON_OBJECT('id', NEW.id, 'designacion_id', NEW.designacion_id, 'articulo_id', NEW.articulo_id, 'sit_rev', NEW.sit_rev, 'disposicion_interna_id', NEW.disposicion_interna_id, 'resolucion_externa_id', NEW.resolucion_externa_id, 'nro_formulario_papel', NEW.nro_formulario_papel, 'fecha_recepcion_formulario', NEW.fecha_recepcion_formulario, 'sello_regional_as', NEW.sello_regional_as, 'justifica', NEW.justifica, 'desde', NEW.desde, 'hasta', NEW.hasta, 'anulada', NEW.anulada, 'observaciones', NEW.observaciones));
END$$

CREATE TRIGGER trg_aud_licencia_otorgada_au AFTER UPDATE ON licencia_otorgada
FOR EACH ROW
BEGIN
  INSERT INTO auditoria (usuario_id, accion, tabla, registro_id, dni_afectado, valor_anterior, valor_nuevo)
  VALUES (fn_usuario_actual(), IF(NEW.anulada = 1 AND OLD.anulada = 0, 'ANULACION', 'MODIFICACION'), 'licencia_otorgada', NEW.id, (SELECT dni FROM designacion WHERE id = NEW.designacion_id), JSON_OBJECT('id', OLD.id, 'designacion_id', OLD.designacion_id, 'articulo_id', OLD.articulo_id, 'sit_rev', OLD.sit_rev, 'disposicion_interna_id', OLD.disposicion_interna_id, 'resolucion_externa_id', OLD.resolucion_externa_id, 'nro_formulario_papel', OLD.nro_formulario_papel, 'fecha_recepcion_formulario', OLD.fecha_recepcion_formulario, 'sello_regional_as', OLD.sello_regional_as, 'justifica', OLD.justifica, 'desde', OLD.desde, 'hasta', OLD.hasta, 'anulada', OLD.anulada, 'observaciones', OLD.observaciones), JSON_OBJECT('id', NEW.id, 'designacion_id', NEW.designacion_id, 'articulo_id', NEW.articulo_id, 'sit_rev', NEW.sit_rev, 'disposicion_interna_id', NEW.disposicion_interna_id, 'resolucion_externa_id', NEW.resolucion_externa_id, 'nro_formulario_papel', NEW.nro_formulario_papel, 'fecha_recepcion_formulario', NEW.fecha_recepcion_formulario, 'sello_regional_as', NEW.sello_regional_as, 'justifica', NEW.justifica, 'desde', NEW.desde, 'hasta', NEW.hasta, 'anulada', NEW.anulada, 'observaciones', NEW.observaciones));
END$$

CREATE TRIGGER trg_aud_licencia_otorgada_ad AFTER DELETE ON licencia_otorgada
FOR EACH ROW
BEGIN
  INSERT INTO auditoria (usuario_id, accion, tabla, registro_id, dni_afectado, valor_anterior, valor_nuevo)
  VALUES (fn_usuario_actual(), 'BAJA', 'licencia_otorgada', OLD.id, (SELECT dni FROM designacion WHERE id = OLD.designacion_id), JSON_OBJECT('id', OLD.id, 'designacion_id', OLD.designacion_id, 'articulo_id', OLD.articulo_id, 'sit_rev', OLD.sit_rev, 'disposicion_interna_id', OLD.disposicion_interna_id, 'resolucion_externa_id', OLD.resolucion_externa_id, 'nro_formulario_papel', OLD.nro_formulario_papel, 'fecha_recepcion_formulario', OLD.fecha_recepcion_formulario, 'sello_regional_as', OLD.sello_regional_as, 'justifica', OLD.justifica, 'desde', OLD.desde, 'hasta', OLD.hasta, 'anulada', OLD.anulada, 'observaciones', OLD.observaciones), NULL);
END$$

CREATE TRIGGER trg_aud_asistencia_ai AFTER INSERT ON asistencia
FOR EACH ROW
BEGIN
  INSERT INTO auditoria (usuario_id, accion, tabla, registro_id, dni_afectado, valor_anterior, valor_nuevo)
  VALUES (fn_usuario_actual(), 'ALTA', 'asistencia', NEW.id, (SELECT dni FROM designacion WHERE id = NEW.designacion_id), NULL, JSON_OBJECT('id', NEW.id, 'designacion_id', NEW.designacion_id, 'fecha', NEW.fecha, 'estado', NEW.estado, 'horas_inasistidas', NEW.horas_inasistidas, 'licencia_otorgada_id', NEW.licencia_otorgada_id, 'estado_justificacion', NEW.estado_justificacion, 'nro_formulario_papel', NEW.nro_formulario_papel, 'observaciones', NEW.observaciones));
END$$

CREATE TRIGGER trg_aud_asistencia_au AFTER UPDATE ON asistencia
FOR EACH ROW
BEGIN
  INSERT INTO auditoria (usuario_id, accion, tabla, registro_id, dni_afectado, valor_anterior, valor_nuevo)
  VALUES (fn_usuario_actual(), 'MODIFICACION', 'asistencia', NEW.id, (SELECT dni FROM designacion WHERE id = NEW.designacion_id), JSON_OBJECT('id', OLD.id, 'designacion_id', OLD.designacion_id, 'fecha', OLD.fecha, 'estado', OLD.estado, 'horas_inasistidas', OLD.horas_inasistidas, 'licencia_otorgada_id', OLD.licencia_otorgada_id, 'estado_justificacion', OLD.estado_justificacion, 'nro_formulario_papel', OLD.nro_formulario_papel, 'observaciones', OLD.observaciones), JSON_OBJECT('id', NEW.id, 'designacion_id', NEW.designacion_id, 'fecha', NEW.fecha, 'estado', NEW.estado, 'horas_inasistidas', NEW.horas_inasistidas, 'licencia_otorgada_id', NEW.licencia_otorgada_id, 'estado_justificacion', NEW.estado_justificacion, 'nro_formulario_papel', NEW.nro_formulario_papel, 'observaciones', NEW.observaciones));
END$$

CREATE TRIGGER trg_aud_asistencia_ad AFTER DELETE ON asistencia
FOR EACH ROW
BEGIN
  INSERT INTO auditoria (usuario_id, accion, tabla, registro_id, dni_afectado, valor_anterior, valor_nuevo)
  VALUES (fn_usuario_actual(), 'BAJA', 'asistencia', OLD.id, (SELECT dni FROM designacion WHERE id = OLD.designacion_id), JSON_OBJECT('id', OLD.id, 'designacion_id', OLD.designacion_id, 'fecha', OLD.fecha, 'estado', OLD.estado, 'horas_inasistidas', OLD.horas_inasistidas, 'licencia_otorgada_id', OLD.licencia_otorgada_id, 'estado_justificacion', OLD.estado_justificacion, 'nro_formulario_papel', OLD.nro_formulario_papel, 'observaciones', OLD.observaciones), NULL);
END$$

CREATE TRIGGER trg_aud_disposicion_ai AFTER INSERT ON disposicion
FOR EACH ROW
BEGIN
  INSERT INTO auditoria (usuario_id, accion, tabla, registro_id, dni_afectado, valor_anterior, valor_nuevo)
  VALUES (fn_usuario_actual(), 'ALTA', 'disposicion', NEW.id, NEW.dni_beneficiario, NULL, JSON_OBJECT('id', NEW.id, 'tipo', NEW.tipo, 'dni_beneficiario', NEW.dni_beneficiario, 'oficina_codigo', NEW.oficina_codigo, 'anio', NEW.anio, 'numero', NEW.numero, 'org_emisor', NEW.org_emisor, 'fecha_emision', NEW.fecha_emision, 'periodo_mes', NEW.periodo_mes, 'anulada', NEW.anulada, 'observaciones', NEW.observaciones));
END$$

CREATE TRIGGER trg_aud_disposicion_au AFTER UPDATE ON disposicion
FOR EACH ROW
BEGIN
  INSERT INTO auditoria (usuario_id, accion, tabla, registro_id, dni_afectado, valor_anterior, valor_nuevo)
  VALUES (fn_usuario_actual(), IF(NEW.anulada = 1 AND OLD.anulada = 0, 'ANULACION', 'MODIFICACION'), 'disposicion', NEW.id, NEW.dni_beneficiario, JSON_OBJECT('id', OLD.id, 'tipo', OLD.tipo, 'dni_beneficiario', OLD.dni_beneficiario, 'oficina_codigo', OLD.oficina_codigo, 'anio', OLD.anio, 'numero', OLD.numero, 'org_emisor', OLD.org_emisor, 'fecha_emision', OLD.fecha_emision, 'periodo_mes', OLD.periodo_mes, 'anulada', OLD.anulada, 'observaciones', OLD.observaciones), JSON_OBJECT('id', NEW.id, 'tipo', NEW.tipo, 'dni_beneficiario', NEW.dni_beneficiario, 'oficina_codigo', NEW.oficina_codigo, 'anio', NEW.anio, 'numero', NEW.numero, 'org_emisor', NEW.org_emisor, 'fecha_emision', NEW.fecha_emision, 'periodo_mes', NEW.periodo_mes, 'anulada', NEW.anulada, 'observaciones', NEW.observaciones));
END$$

CREATE TRIGGER trg_aud_disposicion_ad AFTER DELETE ON disposicion
FOR EACH ROW
BEGIN
  INSERT INTO auditoria (usuario_id, accion, tabla, registro_id, dni_afectado, valor_anterior, valor_nuevo)
  VALUES (fn_usuario_actual(), 'BAJA', 'disposicion', OLD.id, OLD.dni_beneficiario, JSON_OBJECT('id', OLD.id, 'tipo', OLD.tipo, 'dni_beneficiario', OLD.dni_beneficiario, 'oficina_codigo', OLD.oficina_codigo, 'anio', OLD.anio, 'numero', OLD.numero, 'org_emisor', OLD.org_emisor, 'fecha_emision', OLD.fecha_emision, 'periodo_mes', OLD.periodo_mes, 'anulada', OLD.anulada, 'observaciones', OLD.observaciones), NULL);
END$$

CREATE TRIGGER trg_aud_cierre_periodo_ai AFTER INSERT ON cierre_periodo
FOR EACH ROW
BEGIN
  INSERT INTO auditoria (usuario_id, accion, tabla, registro_id, dni_afectado, valor_anterior, valor_nuevo)
  VALUES (fn_usuario_actual(), 'ALTA', 'cierre_periodo', NEW.id, NULL, NULL, JSON_OBJECT('id', NEW.id, 'tipo', NEW.tipo, 'periodo', NEW.periodo, 'estado', NEW.estado, 'cerrado_por', NEW.cerrado_por, 'cerrado_en', NEW.cerrado_en, 'reabierto_por', NEW.reabierto_por, 'reabierto_en', NEW.reabierto_en, 'motivo_reapertura', NEW.motivo_reapertura));
END$$

CREATE TRIGGER trg_aud_cierre_periodo_au AFTER UPDATE ON cierre_periodo
FOR EACH ROW
BEGIN
  INSERT INTO auditoria (usuario_id, accion, tabla, registro_id, dni_afectado, valor_anterior, valor_nuevo)
  VALUES (fn_usuario_actual(), 'MODIFICACION', 'cierre_periodo', NEW.id, NULL, JSON_OBJECT('id', OLD.id, 'tipo', OLD.tipo, 'periodo', OLD.periodo, 'estado', OLD.estado, 'cerrado_por', OLD.cerrado_por, 'cerrado_en', OLD.cerrado_en, 'reabierto_por', OLD.reabierto_por, 'reabierto_en', OLD.reabierto_en, 'motivo_reapertura', OLD.motivo_reapertura), JSON_OBJECT('id', NEW.id, 'tipo', NEW.tipo, 'periodo', NEW.periodo, 'estado', NEW.estado, 'cerrado_por', NEW.cerrado_por, 'cerrado_en', NEW.cerrado_en, 'reabierto_por', NEW.reabierto_por, 'reabierto_en', NEW.reabierto_en, 'motivo_reapertura', NEW.motivo_reapertura));
END$$

CREATE TRIGGER trg_aud_cierre_periodo_ad AFTER DELETE ON cierre_periodo
FOR EACH ROW
BEGIN
  INSERT INTO auditoria (usuario_id, accion, tabla, registro_id, dni_afectado, valor_anterior, valor_nuevo)
  VALUES (fn_usuario_actual(), 'BAJA', 'cierre_periodo', OLD.id, NULL, JSON_OBJECT('id', OLD.id, 'tipo', OLD.tipo, 'periodo', OLD.periodo, 'estado', OLD.estado, 'cerrado_por', OLD.cerrado_por, 'cerrado_en', OLD.cerrado_en, 'reabierto_por', OLD.reabierto_por, 'reabierto_en', OLD.reabierto_en, 'motivo_reapertura', OLD.motivo_reapertura), NULL);
END$$

DELIMITER ;
-- =============================================================================
-- 8. VISTAS DE CONSULTA (RF-12, RF-13, RF-17, RF-18)
-- =============================================================================
-- Desglose mensual por materia / cargo: días y horas afectadas.
CREATE VIEW v_inasistencia_mensual AS
SELECT p.dni, p.apellido_nombre, d.id AS designacion_id, c.descripcion AS cargo,
       ec.nombre AS espacio_curricular, YEAR(a.fecha) AS anio, MONTH(a.fecha) AS mes,
       SUM(a.estado = 'I')   AS dias_inasistencia,
       SUM(a.estado = 'LIC') AS dias_licencia,
       SUM(a.estado = 'LT')  AS dias_largo_tratamiento,
       SUM(a.estado = 'PR')  AS dias_presente_retirado,
       SUM(a.horas_inasistidas) AS horas_afectadas
  FROM asistencia a
  JOIN designacion d ON d.id = a.designacion_id
  JOIN personal p    ON p.dni = d.dni
  JOIN cargo c       ON c.id = d.cargo_id
  LEFT JOIN espacio_curricular ec ON ec.id = d.espacio_curricular_id
 WHERE a.estado <> 'P'
 GROUP BY p.dni, p.apellido_nombre, d.id, c.descripcion, ec.nombre, YEAR(a.fecha), MONTH(a.fecha);

-- Días de licencia usados por agente, artículo y año, frente al tope anual (RN-08).
-- Cuenta una sola vez cada fecha aunque el docente tenga varias designaciones.
-- Limitación: solo topes en DIAS "POR_ANIO"; no evalúa antigüedad ni topes por vez.
CREATE VIEW v_licencia_acumulada AS
SELECT d.dni, lo.articulo_id, la.cod_licencia, la.tipo_licencia, la.categoria_informe,
       YEAR(a.fecha) AS anio,
       COUNT(DISTINCT a.fecha) AS dias_usados,
       la.tope_cantidad AS tope_anual,
       CASE WHEN la.tope_unidad = 'DIAS' AND la.tope_periodo = 'POR_ANIO' AND la.tope_cantidad > 0
            THEN ROUND(100 * COUNT(DISTINCT a.fecha) / la.tope_cantidad, 1) END AS porcentaje_tope
  FROM asistencia a
  JOIN licencia_otorgada lo ON lo.id = a.licencia_otorgada_id AND lo.anulada = 0
  JOIN designacion d        ON d.id = lo.designacion_id
  JOIN licencia_articulo la ON la.id = lo.articulo_id
 WHERE a.estado IN ('LIC','LT')
 GROUP BY d.dni, lo.articulo_id, la.cod_licencia, la.tipo_licencia, la.categoria_informe,
          YEAR(a.fecha), la.tope_cantidad, la.tope_unidad, la.tope_periodo;

-- Alertas preventivas (RF-18): agentes que alcanzaron el umbral configurado en parametro.
CREATE VIEW v_alerta_topes AS
SELECT v.*, p.apellido_nombre
  FROM v_licencia_acumulada v
  JOIN personal p ON p.dni = v.dni
 WHERE v.porcentaje_tope IS NOT NULL
   AND v.porcentaje_tope >= (SELECT CAST(valor AS DECIMAL(5,2)) FROM parametro WHERE clave = 'umbral_alerta_pct');

-- =============================================================================
-- 9. PROCEDIMIENTOS
-- =============================================================================
DELIMITER $$

-- Propaga una licencia (RN-07, RF-14): marca LIC o LT en cada día hábil del período en que
-- la designación tiene clase según su horario, con las horas afectadas (RF-13). Omite fines
-- de semana, el calendario escolar (RF-10) y días fuera de la vigencia de la designación.
-- Atención: usa una transacción propia (confirma la transacción abierta del llamador).
CREATE PROCEDURE sp_propagar_licencia(IN p_licencia_id INT)
BEGIN
  DECLARE v_desig INT; DECLARE v_desde DATE; DECLARE v_hasta DATE; DECLARE v_anulada TINYINT;
  DECLARE v_estado VARCHAR(3); DECLARE v_f DATE; DECLARE v_total INT DEFAULT 0;
  DECLARE v_dia VARCHAR(3);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;

  SELECT lo.designacion_id, lo.desde, lo.hasta, lo.anulada,
         IF(la.es_largo_tratamiento, 'LT', 'LIC')
    INTO v_desig, v_desde, v_hasta, v_anulada, v_estado
    FROM licencia_otorgada lo JOIN licencia_articulo la ON la.id = lo.articulo_id
   WHERE lo.id = p_licencia_id;
  IF v_desig IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La licencia no existe';
  END IF;
  IF v_anulada = 1 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La licencia esta anulada';
  END IF;
  IF v_hasta IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La licencia no tiene fecha hasta: no se puede propagar';
  END IF;

  START TRANSACTION;
  SET v_f = v_desde;
  WHILE v_f <= v_hasta DO
    SET v_dia = ELT(WEEKDAY(v_f) + 1, 'LUN','MAR','MIE','JUE','VIE','SAB','DOM');
    IF fn_vigente_en(v_desig, v_f)
       AND NOT EXISTS (SELECT 1 FROM calendario_escolar WHERE fecha = v_f) THEN
      INSERT INTO asistencia (designacion_id, fecha, estado, horas_inasistidas, licencia_otorgada_id)
      SELECT v_desig, v_f, v_estado, SUM(h.horas_catedra), p_licencia_id
        FROM horario h
       WHERE h.designacion_id = v_desig AND h.dia = v_dia
      HAVING COUNT(*) > 0
      ON DUPLICATE KEY UPDATE estado = VALUES(estado), horas_inasistidas = VALUES(horas_inasistidas),
                              licencia_otorgada_id = VALUES(licencia_otorgada_id),
                              estado_justificacion = NULL;
      SET v_total = v_total + ROW_COUNT();
    END IF;
    SET v_f = v_f + INTERVAL 1 DAY;
  END WHILE;
  COMMIT;
  SELECT v_total AS filas_afectadas;
END$$

-- Numeración correlativa de disposiciones internas (RF-16, RN-11): una disposición por agente
-- con licencias del mes sin disposición y con formulario en papel (RN-10), ordenadas
-- alfabéticamente por apellido y nombre; la numeración continúa la del año y la oficina.
-- Criterio propuesto (una disposición por agente y mes): confirmar con el cliente.
CREATE PROCEDURE sp_asignar_disposiciones(IN p_anio SMALLINT, IN p_mes TINYINT, IN p_oficina VARCHAR(10))
BEGIN
  DECLARE v_done INT DEFAULT 0; DECLARE v_dni VARCHAR(10); DECLARE v_num INT; DECLARE v_id INT;
  DECLARE v_ini DATE; DECLARE v_fin DATE;
  DECLARE cur CURSOR FOR
    SELECT p.dni FROM personal p
     WHERE EXISTS (SELECT 1 FROM licencia_otorgada lo JOIN designacion d ON d.id = lo.designacion_id
                    WHERE d.dni = p.dni AND lo.anulada = 0 AND lo.disposicion_interna_id IS NULL
                      AND lo.nro_formulario_papel IS NOT NULL
                      AND lo.desde <= v_fin AND COALESCE(lo.hasta, lo.desde) >= v_ini)
     ORDER BY p.apellido, p.nombres, p.dni;
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_done = 1;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;

  SET v_ini = STR_TO_DATE(CONCAT(p_anio, '-', p_mes, '-01'), '%Y-%m-%d');
  SET v_fin = LAST_DAY(v_ini);
  START TRANSACTION;
  SELECT COALESCE(MAX(numero), 0) INTO v_num FROM disposicion
   WHERE tipo = 'INTERNA' AND oficina_codigo = p_oficina AND anio = p_anio FOR UPDATE;

  OPEN cur;
  lp: LOOP
    FETCH cur INTO v_dni;
    IF v_done THEN LEAVE lp; END IF;
    SET v_num = v_num + 1;
    INSERT INTO disposicion (tipo, dni_beneficiario, oficina_codigo, anio, numero, fecha_emision, periodo_mes)
    VALUES ('INTERNA', v_dni, p_oficina, p_anio, v_num, CURRENT_DATE, p_mes);
    SET v_id = LAST_INSERT_ID();
    UPDATE licencia_otorgada lo JOIN designacion d ON d.id = lo.designacion_id
       SET lo.disposicion_interna_id = v_id
     WHERE d.dni = v_dni AND lo.anulada = 0 AND lo.disposicion_interna_id IS NULL
       AND lo.nro_formulario_papel IS NOT NULL
       AND lo.desde <= v_fin AND COALESCE(lo.hasta, lo.desde) >= v_ini;
  END LOOP;
  CLOSE cur;
  COMMIT;
  SELECT COUNT(*) AS disposiciones_emitidas FROM disposicion
   WHERE tipo = 'INTERNA' AND oficina_codigo = p_oficina AND anio = p_anio AND periodo_mes = p_mes;
END$$

DELIMITER ;

-- =============================================================================
-- 10. DATOS INICIALES (a confirmar con el cliente)
-- =============================================================================
INSERT INTO rol (codigo, nombre) VALUES
  ('BEDEL',         'Bedel'),
  ('SECRETARIA',    'Secretaría'),
  ('SUBSECRETARIA', 'Subsecretaría'),
  ('RECTOR',        'Rector'),
  ('SUBRECTOR',     'Subrector'),
  ('DESARROLLADOR', 'Desarrollador (temporal)');

INSERT INTO permiso (codigo, descripcion) VALUES
  ('ASISTENCIA_CARGAR',      'Cargar asistencia diaria y corregir el día abierto'),
  ('FORMULARIO_RECEPCIONAR', 'Registrar la recepción de formularios en papel'),
  ('LICENCIA_CARGAR',        'Cargar y editar licencias'),
  ('CIERRE_REABRIR',         'Corregir tras el cierre diario o mensual y reabrir (RN-06)'),
  ('DISPOSICION_EMITIR',     'Emitir disposiciones y cerrar el mes'),
  ('CATALOGOS_ADMIN',        'Administrar catálogos, importar CSV y calendario'),
  ('CONSULTAR',              'Consultas y alertas'),
  ('AUDITORIA_VER',          'Ver la bitácora de auditoría'),
  ('USUARIOS_ADMIN',         'Administrar usuarios y parámetros');

-- Rector y Subrector: solo consulta y auditoría hasta que el cliente indique qué necesitan.
INSERT INTO rol_permiso (rol_id, permiso_codigo)
SELECT r.id, p.codigo FROM rol r JOIN permiso p ON
     (r.codigo = 'BEDEL' AND p.codigo IN ('ASISTENCIA_CARGAR','FORMULARIO_RECEPCIONAR','CONSULTAR'))
  OR (r.codigo IN ('SECRETARIA','SUBSECRETARIA') AND p.codigo <> 'USUARIOS_ADMIN')
  OR (r.codigo IN ('RECTOR','SUBRECTOR') AND p.codigo IN ('CONSULTAR','AUDITORIA_VER'))
  OR (r.codigo = 'DESARROLLADOR');

-- Usuario técnico para operaciones sin usuario identificado (cargas masivas, pruebas).
INSERT INTO usuario (rol_id, username, password_hash, apellido, nombres, activo)
SELECT id, 'sistema', '!', 'Sistema', 'Automático', FALSE FROM rol WHERE codigo = 'DESARROLLADOR';

INSERT INTO situacion_revista (codigo, descripcion) VALUES
  ('TITULAR',  'Titular'),
  ('INTERINO', 'Interino'),
  ('SUPLENTE', 'Suplente');

INSERT INTO parametro (clave, valor, descripcion) VALUES
  ('nombre_institucion', 'IESETyFP', 'Nombre de la institución'),
  ('oficina_codigo',     '1452',     'Código de oficina por defecto (IESETyFP)'),
  ('oficina_anexo',      '0',        'Código de anexo'),
  ('ciclo_lectivo',      '2026',     'Año operativo en curso'),
  ('umbral_alerta_pct',  '80',       'Porcentaje del tope a partir del cual se emite alerta (RF-18) - A CONFIRMAR');
