-- =============================================================================
-- Datos de prueba — Sistema de Asistencia Docente (MariaDB / MySQL)
-- =============================================================================
-- Antes de correrlo:
--   1) python manage.py migrate     (crea las tablas, las marcas P/I/LIC/LT/PR y los 3 roles)
--   2) USE asistencia;              (o el nombre de tu base)
-- Qué carga:
--   * 3 carreras y 12 materias          * 2 cargos (HC y COORD)
--   * 20 docentes (DNI 99000001 a 99000020) y 22 designaciones con horarios
--   * 5 artículos de licencia con tope anual y 12 licencias otorgadas
--   * 11 feriados 2026                  * 35 registros de asistencia de octubre 2026
--   * 9 usuarios del sistema (3 Bedelía, 3 Secretaría, 3 Subsecretaría)
-- Contraseña de todos los usuarios: Prueba2026!
-- Es 100 % ficticio. Se corre UNA vez (los datos con id fijo fallan si ya existen).
-- Para borrar lo cargado mirá el bloque de limpieza al final.
-- =============================================================================
SET NAMES utf8mb4;
START TRANSACTION;

-- ───────────── Carreras ─────────────
INSERT IGNORE INTO personal_carrera (nombre, plan_estudio, anio_plan, activa) VALUES
  ('Desarrollo de Software', 'Plan 2019', 2019, 1),
  ('Higiene y Seguridad en el Trabajo', 'Plan 2018', 2018, 1),
  ('Gestión Administrativa', 'Plan 2020', 2020, 1);

-- ───────────── Materias (espacios curriculares) ─────────────
INSERT IGNORE INTO personal_espacio_curricular (nombre, carrera_id, activo) VALUES
  ('Programación I', (SELECT id FROM personal_carrera WHERE nombre = 'Desarrollo de Software'), 1),
  ('Bases de Datos', (SELECT id FROM personal_carrera WHERE nombre = 'Desarrollo de Software'), 1),
  ('Ingeniería de Software', (SELECT id FROM personal_carrera WHERE nombre = 'Desarrollo de Software'), 1),
  ('Testing de Software', (SELECT id FROM personal_carrera WHERE nombre = 'Desarrollo de Software'), 1),
  ('Riesgos Laborales', (SELECT id FROM personal_carrera WHERE nombre = 'Higiene y Seguridad en el Trabajo'), 1),
  ('Legislación Laboral', (SELECT id FROM personal_carrera WHERE nombre = 'Higiene y Seguridad en el Trabajo'), 1),
  ('Ergonomía', (SELECT id FROM personal_carrera WHERE nombre = 'Higiene y Seguridad en el Trabajo'), 1),
  ('Primeros Auxilios', (SELECT id FROM personal_carrera WHERE nombre = 'Higiene y Seguridad en el Trabajo'), 1),
  ('Contabilidad', (SELECT id FROM personal_carrera WHERE nombre = 'Gestión Administrativa'), 1),
  ('Administración General', (SELECT id FROM personal_carrera WHERE nombre = 'Gestión Administrativa'), 1),
  ('Derecho Comercial', (SELECT id FROM personal_carrera WHERE nombre = 'Gestión Administrativa'), 1),
  ('Gestión de Personal', (SELECT id FROM personal_carrera WHERE nombre = 'Gestión Administrativa'), 1);

-- ───────────── Cargos ─────────────
INSERT IGNORE INTO personal_cargo (codigo, descripcion, es_docente, activo) VALUES
  ('HC', 'Horas cátedra', 1, 1),
  ('COORD', 'Coordinador de carrera', 1, 1);

-- ───────────── Personas (docentes de prueba, DNI 99000001 a 99000020) ─────────────
INSERT IGNORE INTO personal_persona (dni, apellido_nombre, apellido, nombres, tipo_documento, sexo, fecha_nacimiento, estado_civil, nacionalidad, nro_dgi, nro_dgr, domicilio_calle, barrio, localidad, codigo_postal, provincia, telefono, email, activa) VALUES
  ('99000001', 'ACOSTA, María Laura', 'Acosta', 'María Laura', 'DNI', 'F', '1973-02-08', '', 'Argentina', '', '', '', '', 'Corrientes', '', 'Corrientes', '3794000001', 'acosta1@ejemplo.test', 1),
  ('99000002', 'BENÍTEZ, Carlos Alberto', 'Benítez', 'Carlos Alberto', 'DNI', 'M', '1976-03-15', '', 'Argentina', '', '', '', '', 'Resistencia', '', 'Chaco', '3794000002', 'benitez2@ejemplo.test', 1),
  ('99000003', 'CABRERA, Silvana', 'Cabrera', 'Silvana', 'DNI', 'F', '1979-04-22', '', 'Argentina', '', '', '', '', 'Corrientes', '', 'Corrientes', '3794000003', 'cabrera3@ejemplo.test', 1),
  ('99000004', 'DOMÍNGUEZ, Federico', 'Domínguez', 'Federico', 'DNI', 'M', '1982-05-01', '', 'Argentina', '', '', '', '', 'Resistencia', '', 'Chaco', '3794000004', 'dominguez4@ejemplo.test', 1),
  ('99000005', 'ESCOBAR, Natalia', 'Escobar', 'Natalia', 'DNI', 'F', '1985-06-08', '', 'Argentina', '', '', '', '', 'Corrientes', '', 'Corrientes', '3794000005', 'escobar5@ejemplo.test', 1),
  ('99000006', 'FERNÁNDEZ, Gustavo', 'Fernández', 'Gustavo', 'DNI', 'M', '1988-07-15', '', 'Argentina', '', '', '', '', 'Resistencia', '', 'Chaco', '3794000006', 'fernández6@ejemplo.test', 1),
  ('99000007', 'GÓMEZ, Lucía', 'Gómez', 'Lucía', 'DNI', 'F', '1991-08-22', '', 'Argentina', '', '', '', '', 'Corrientes', '', 'Corrientes', '3794000007', 'gómez7@ejemplo.test', 1),
  ('99000008', 'HERRERA, Matías', 'Herrera', 'Matías', 'DNI', 'M', '1994-09-01', '', 'Argentina', '', '', '', '', 'Resistencia', '', 'Chaco', '3794000008', 'herrera8@ejemplo.test', 1),
  ('99000009', 'INSAURRALDE, Carolina', 'Insaurralde', 'Carolina', 'DNI', 'F', '1997-10-08', '', 'Argentina', '', '', '', '', 'Corrientes', '', 'Corrientes', '3794000009', 'insaurralde9@ejemplo.test', 1),
  ('99000010', 'JARA, Sebastián', 'Jara', 'Sebastián', 'DNI', 'M', '1970-11-15', '', 'Argentina', '', '', '', '', 'Resistencia', '', 'Chaco', '3794000010', 'jara10@ejemplo.test', 1),
  ('99000011', 'KRIEGER, Valeria', 'Krieger', 'Valeria', 'DNI', 'F', '1973-12-22', '', 'Argentina', '', '', '', '', 'Corrientes', '', 'Corrientes', '3794000011', 'krieger11@ejemplo.test', 1),
  ('99000012', 'LÓPEZ, Diego', 'López', 'Diego', 'DNI', 'M', '1976-01-01', '', 'Argentina', '', '', '', '', 'Resistencia', '', 'Chaco', '3794000012', 'lópez12@ejemplo.test', 1),
  ('99000013', 'MAIDANA, Romina', 'Maidana', 'Romina', 'DNI', 'F', '1979-02-08', '', 'Argentina', '', '', '', '', 'Corrientes', '', 'Corrientes', '3794000013', 'maidana13@ejemplo.test', 1),
  ('99000014', 'NÚÑEZ, Pablo', 'Núñez', 'Pablo', 'DNI', 'M', '1982-03-15', '', 'Argentina', '', '', '', '', 'Resistencia', '', 'Chaco', '3794000014', 'nunez14@ejemplo.test', 1),
  ('99000015', 'OJEDA, Florencia', 'Ojeda', 'Florencia', 'DNI', 'F', '1985-04-22', '', 'Argentina', '', '', '', '', 'Corrientes', '', 'Corrientes', '3794000015', 'ojeda15@ejemplo.test', 1),
  ('99000016', 'PEREYRA, Ramón', 'Pereyra', 'Ramón', 'DNI', 'M', '1988-05-01', '', 'Argentina', '', '', '', '', 'Resistencia', '', 'Chaco', '3794000016', 'pereyra16@ejemplo.test', 1),
  ('99000017', 'QUIROGA, Mariana', 'Quiroga', 'Mariana', 'DNI', 'F', '1991-06-08', '', 'Argentina', '', '', '', '', 'Corrientes', '', 'Corrientes', '3794000017', 'quiroga17@ejemplo.test', 1),
  ('99000018', 'ROMERO, Alejandro', 'Romero', 'Alejandro', 'DNI', 'M', '1994-07-15', '', 'Argentina', '', '', '', '', 'Resistencia', '', 'Chaco', '3794000018', 'romero18@ejemplo.test', 1),
  ('99000019', 'SOSA, Paola', 'Sosa', 'Paola', 'DNI', 'F', '1997-08-22', '', 'Argentina', '', '', '', '', 'Corrientes', '', 'Corrientes', '3794000019', 'sosa19@ejemplo.test', 1),
  ('99000020', 'VILLALBA, Joaquín', 'Villalba', 'Joaquín', 'DNI', 'M', '1970-09-01', '', 'Argentina', '', '', '', '', 'Resistencia', '', 'Chaco', '3794000020', 'villalba20@ejemplo.test', 1);

-- ───────────── Designaciones (ids 9001 a 9022; entran por SQL, por eso no generan historial) ─────────────
INSERT INTO personal_designacion (id, persona_id, cargo_id, espacio_curricular_id, unidad_educativa_id, especialidad_id, reemplaza_id, situacion_revista, anio_curso, division_seccion, turno, hs_catedra, jornada, disp_alta_nro, sello_regional_as, motivo_id, norma_tipo, norma_numero, norma_anio, organismo_emisor, desde, hasta, pof, anio_pof, novedad, activo, observaciones) VALUES
  (9001, '99000001', 'HC', (SELECT e.id FROM personal_espacio_curricular e JOIN personal_carrera c ON c.id = e.carrera_id WHERE e.nombre = 'Programación I' AND c.nombre = 'Desarrollo de Software'), NULL, NULL, NULL, 'TIT', '2°', 'A', 'Noche', 6, '', '', '', NULL, 'Resolución', '100', 2026, 'Ministerio de Educación', '2026-03-02', NULL, '', NULL, '', 1, 'Dato de prueba'),
  (9002, '99000002', 'HC', (SELECT e.id FROM personal_espacio_curricular e JOIN personal_carrera c ON c.id = e.carrera_id WHERE e.nombre = 'Bases de Datos' AND c.nombre = 'Desarrollo de Software'), NULL, NULL, NULL, 'TIT', '1°', 'A', 'Noche', 6, '', '', '', NULL, 'Resolución', '101', 2026, 'Ministerio de Educación', '2026-03-02', NULL, '', NULL, '', 1, 'Dato de prueba'),
  (9003, '99000003', 'HC', (SELECT e.id FROM personal_espacio_curricular e JOIN personal_carrera c ON c.id = e.carrera_id WHERE e.nombre = 'Ingeniería de Software' AND c.nombre = 'Desarrollo de Software'), NULL, NULL, NULL, 'INT', '2°', 'A', 'Noche', 4, '', '', '', NULL, 'Resolución', '102', 2026, 'Ministerio de Educación', '2026-03-02', NULL, '', NULL, '', 1, 'Dato de prueba'),
  (9004, '99000004', 'HC', (SELECT e.id FROM personal_espacio_curricular e JOIN personal_carrera c ON c.id = e.carrera_id WHERE e.nombre = 'Testing de Software' AND c.nombre = 'Desarrollo de Software'), NULL, NULL, NULL, 'INT', '1°', 'A', 'Tarde', 4, '', '', '', NULL, 'Resolución', '103', 2026, 'Ministerio de Educación', '2026-03-02', NULL, '', NULL, '', 1, 'Dato de prueba'),
  (9005, '99000005', 'HC', (SELECT e.id FROM personal_espacio_curricular e JOIN personal_carrera c ON c.id = e.carrera_id WHERE e.nombre = 'Riesgos Laborales' AND c.nombre = 'Higiene y Seguridad en el Trabajo'), NULL, NULL, NULL, 'TIT', '2°', 'A', 'Tarde', 6, '', '', '', NULL, 'Resolución', '104', 2026, 'Ministerio de Educación', '2026-03-02', NULL, '', NULL, '', 1, 'Dato de prueba'),
  (9006, '99000006', 'HC', (SELECT e.id FROM personal_espacio_curricular e JOIN personal_carrera c ON c.id = e.carrera_id WHERE e.nombre = 'Legislación Laboral' AND c.nombre = 'Higiene y Seguridad en el Trabajo'), NULL, NULL, NULL, 'TIT', '1°', 'A', 'Noche', 4, '', '', '', NULL, 'Resolución', '105', 2026, 'Ministerio de Educación', '2026-03-02', NULL, '', NULL, '', 1, 'Dato de prueba'),
  (9007, '99000007', 'HC', (SELECT e.id FROM personal_espacio_curricular e JOIN personal_carrera c ON c.id = e.carrera_id WHERE e.nombre = 'Ergonomía' AND c.nombre = 'Higiene y Seguridad en el Trabajo'), NULL, NULL, NULL, 'INT', '2°', 'A', 'Tarde', 4, '', '', '', NULL, 'Resolución', '106', 2026, 'Ministerio de Educación', '2026-03-02', NULL, '', NULL, '', 1, 'Dato de prueba'),
  (9008, '99000008', 'HC', (SELECT e.id FROM personal_espacio_curricular e JOIN personal_carrera c ON c.id = e.carrera_id WHERE e.nombre = 'Primeros Auxilios' AND c.nombre = 'Higiene y Seguridad en el Trabajo'), NULL, NULL, NULL, 'SUP', '1°', 'A', 'Tarde', 3, '', '', '', NULL, 'Resolución', '107', 2026, 'Ministerio de Educación', '2026-03-02', '2026-12-18', '', NULL, '', 1, 'Dato de prueba'),
  (9009, '99000009', 'HC', (SELECT e.id FROM personal_espacio_curricular e JOIN personal_carrera c ON c.id = e.carrera_id WHERE e.nombre = 'Contabilidad' AND c.nombre = 'Gestión Administrativa'), NULL, NULL, NULL, 'TIT', '2°', 'A', 'Noche', 6, '', '', '', NULL, 'Resolución', '108', 2026, 'Ministerio de Educación', '2026-03-02', NULL, '', NULL, '', 1, 'Dato de prueba'),
  (9010, '99000010', 'HC', (SELECT e.id FROM personal_espacio_curricular e JOIN personal_carrera c ON c.id = e.carrera_id WHERE e.nombre = 'Administración General' AND c.nombre = 'Gestión Administrativa'), NULL, NULL, NULL, 'TIT', '1°', 'A', 'Noche', 4, '', '', '', NULL, 'Resolución', '109', 2026, 'Ministerio de Educación', '2026-03-02', NULL, '', NULL, '', 1, 'Dato de prueba'),
  (9011, '99000011', 'HC', (SELECT e.id FROM personal_espacio_curricular e JOIN personal_carrera c ON c.id = e.carrera_id WHERE e.nombre = 'Derecho Comercial' AND c.nombre = 'Gestión Administrativa'), NULL, NULL, NULL, 'INT', '2°', 'A', 'Noche', 4, '', '', '', NULL, 'Resolución', '110', 2026, 'Ministerio de Educación', '2026-03-02', NULL, '', NULL, '', 1, 'Dato de prueba'),
  (9012, '99000012', 'HC', (SELECT e.id FROM personal_espacio_curricular e JOIN personal_carrera c ON c.id = e.carrera_id WHERE e.nombre = 'Gestión de Personal' AND c.nombre = 'Gestión Administrativa'), NULL, NULL, NULL, 'SUP', '1°', 'A', 'Tarde', 3, '', '', '', NULL, 'Resolución', '111', 2026, 'Ministerio de Educación', '2026-03-02', '2026-12-18', '', NULL, '', 1, 'Dato de prueba'),
  (9013, '99000013', 'HC', (SELECT e.id FROM personal_espacio_curricular e JOIN personal_carrera c ON c.id = e.carrera_id WHERE e.nombre = 'Programación I' AND c.nombre = 'Desarrollo de Software'), NULL, NULL, NULL, 'SUP', '2°', 'A', 'Tarde', 4, '', '', '', NULL, 'Resolución', '112', 2026, 'Ministerio de Educación', '2026-03-02', '2026-12-18', '', NULL, '', 1, 'Dato de prueba'),
  (9014, '99000014', 'HC', (SELECT e.id FROM personal_espacio_curricular e JOIN personal_carrera c ON c.id = e.carrera_id WHERE e.nombre = 'Bases de Datos' AND c.nombre = 'Desarrollo de Software'), NULL, NULL, NULL, 'INT', '1°', 'A', 'Tarde', 4, '', '', '', NULL, 'Resolución', '113', 2026, 'Ministerio de Educación', '2026-03-02', NULL, '', NULL, '', 1, 'Dato de prueba'),
  (9015, '99000015', 'HC', (SELECT e.id FROM personal_espacio_curricular e JOIN personal_carrera c ON c.id = e.carrera_id WHERE e.nombre = 'Testing de Software' AND c.nombre = 'Desarrollo de Software'), NULL, NULL, NULL, 'TIT', '2°', 'A', 'Noche', 4, '', '', '', NULL, 'Resolución', '114', 2026, 'Ministerio de Educación', '2026-03-02', NULL, '', NULL, '', 1, 'Dato de prueba'),
  (9016, '99000016', 'HC', (SELECT e.id FROM personal_espacio_curricular e JOIN personal_carrera c ON c.id = e.carrera_id WHERE e.nombre = 'Riesgos Laborales' AND c.nombre = 'Higiene y Seguridad en el Trabajo'), NULL, NULL, NULL, 'INT', '1°', 'A', 'Noche', 4, '', '', '', NULL, 'Resolución', '115', 2026, 'Ministerio de Educación', '2026-03-02', NULL, '', NULL, '', 1, 'Dato de prueba'),
  (9017, '99000017', 'HC', (SELECT e.id FROM personal_espacio_curricular e JOIN personal_carrera c ON c.id = e.carrera_id WHERE e.nombre = 'Contabilidad' AND c.nombre = 'Gestión Administrativa'), NULL, NULL, NULL, 'SUP', '2°', 'A', 'Tarde', 3, '', '', '', NULL, 'Resolución', '116', 2026, 'Ministerio de Educación', '2026-03-02', '2026-12-18', '', NULL, '', 1, 'Dato de prueba'),
  (9018, '99000018', 'HC', (SELECT e.id FROM personal_espacio_curricular e JOIN personal_carrera c ON c.id = e.carrera_id WHERE e.nombre = 'Ingeniería de Software' AND c.nombre = 'Desarrollo de Software'), NULL, NULL, NULL, 'TIT', '1°', 'A', 'Noche', 6, '', '', '', NULL, 'Resolución', '117', 2026, 'Ministerio de Educación', '2026-03-02', NULL, '', NULL, '', 1, 'Dato de prueba'),
  (9019, '99000019', 'HC', (SELECT e.id FROM personal_espacio_curricular e JOIN personal_carrera c ON c.id = e.carrera_id WHERE e.nombre = 'Ergonomía' AND c.nombre = 'Higiene y Seguridad en el Trabajo'), NULL, NULL, NULL, 'TIT', '2°', 'A', 'Noche', 4, '', '', '', NULL, 'Resolución', '118', 2026, 'Ministerio de Educación', '2026-03-02', NULL, '', NULL, '', 1, 'Dato de prueba'),
  (9020, '99000020', 'HC', (SELECT e.id FROM personal_espacio_curricular e JOIN personal_carrera c ON c.id = e.carrera_id WHERE e.nombre = 'Derecho Comercial' AND c.nombre = 'Gestión Administrativa'), NULL, NULL, NULL, 'SUP', '1°', 'A', 'Tarde', 3, '', '', '', NULL, 'Resolución', '119', 2026, 'Ministerio de Educación', '2026-03-02', '2026-12-18', '', NULL, '', 1, 'Dato de prueba'),
  (9021, '99000001', 'HC', (SELECT e.id FROM personal_espacio_curricular e JOIN personal_carrera c ON c.id = e.carrera_id WHERE e.nombre = 'Ingeniería de Software' AND c.nombre = 'Desarrollo de Software'), NULL, NULL, NULL, 'TIT', '2°', 'A', 'Noche', 4, '', '', '', NULL, 'Resolución', '120', 2026, 'Ministerio de Educación', '2026-03-02', NULL, '', NULL, '', 1, 'Dato de prueba'),
  (9022, '99000009', 'HC', (SELECT e.id FROM personal_espacio_curricular e JOIN personal_carrera c ON c.id = e.carrera_id WHERE e.nombre = 'Gestión de Personal' AND c.nombre = 'Gestión Administrativa'), NULL, NULL, NULL, 'TIT', '1°', 'A', 'Noche', 4, '', '', '', NULL, 'Resolución', '121', 2026, 'Ministerio de Educación', '2026-03-02', NULL, '', NULL, '', 1, 'Dato de prueba');

-- ───────────── Horarios por designación ─────────────
INSERT INTO personal_horario (designacion_id, dia, horas_catedra, hora_inicio, hora_fin) VALUES
  (9001, 'LUN', 3, '18:00:00', '20:00:00'),
  (9001, 'MIE', 3, '18:00:00', '19:30:00'),
  (9002, 'MAR', 3, '18:00:00', '20:00:00'),
  (9002, 'JUE', 3, '18:00:00', '19:30:00'),
  (9003, 'MIE', 2, '18:00:00', '20:00:00'),
  (9003, 'VIE', 2, '18:00:00', '19:30:00'),
  (9004, 'JUE', 2, '18:00:00', '20:00:00'),
  (9004, 'LUN', 2, '18:00:00', '19:30:00'),
  (9005, 'VIE', 3, '18:00:00', '20:00:00'),
  (9005, 'MAR', 3, '18:00:00', '19:30:00'),
  (9006, 'LUN', 2, '18:00:00', '20:00:00'),
  (9006, 'MIE', 2, '18:00:00', '19:30:00'),
  (9007, 'MAR', 2, '18:00:00', '20:00:00'),
  (9007, 'JUE', 2, '18:00:00', '19:30:00'),
  (9008, 'MIE', 2, '18:00:00', '20:00:00'),
  (9008, 'VIE', 1, '18:00:00', '19:30:00'),
  (9009, 'JUE', 3, '18:00:00', '20:00:00'),
  (9009, 'LUN', 3, '18:00:00', '19:30:00'),
  (9010, 'VIE', 2, '18:00:00', '20:00:00'),
  (9010, 'MAR', 2, '18:00:00', '19:30:00'),
  (9011, 'LUN', 2, '18:00:00', '20:00:00'),
  (9011, 'MIE', 2, '18:00:00', '19:30:00'),
  (9012, 'MAR', 2, '18:00:00', '20:00:00'),
  (9012, 'JUE', 1, '18:00:00', '19:30:00'),
  (9013, 'MIE', 2, '18:00:00', '20:00:00'),
  (9013, 'VIE', 2, '18:00:00', '19:30:00'),
  (9014, 'JUE', 2, '18:00:00', '20:00:00'),
  (9014, 'LUN', 2, '18:00:00', '19:30:00'),
  (9015, 'VIE', 2, '18:00:00', '20:00:00'),
  (9015, 'MAR', 2, '18:00:00', '19:30:00'),
  (9016, 'LUN', 2, '18:00:00', '20:00:00'),
  (9016, 'MIE', 2, '18:00:00', '19:30:00'),
  (9017, 'MAR', 2, '18:00:00', '20:00:00'),
  (9017, 'JUE', 1, '18:00:00', '19:30:00'),
  (9018, 'MIE', 3, '18:00:00', '20:00:00'),
  (9018, 'VIE', 3, '18:00:00', '19:30:00'),
  (9019, 'JUE', 2, '18:00:00', '20:00:00'),
  (9019, 'LUN', 2, '18:00:00', '19:30:00'),
  (9020, 'VIE', 2, '18:00:00', '20:00:00'),
  (9020, 'MAR', 1, '18:00:00', '19:30:00'),
  (9021, 'LUN', 2, '18:00:00', '20:00:00'),
  (9021, 'MIE', 2, '18:00:00', '19:30:00'),
  (9022, 'MAR', 2, '18:00:00', '20:00:00'),
  (9022, 'JUE', 2, '18:00:00', '19:30:00');

-- ───────────── Artículos de licencia (con tope anual de días para probar las alertas) ─────────────
INSERT IGNORE INTO licencia_articulo (cod_licencia, articulo, clase, tipo_licencia, categoria_informe, sit_rev, goce_haberes, autoridad, plazo, tope_dias_anual) VALUES
  ('T-14', '14', 'Licencia', 'Enfermedad común', 'Enfermedad común', 'Titular', 'Con goce de haberes', 'Dirección', 'Según artículo', 30),
  ('T-15', '15', 'Licencia', 'Largo tratamiento', 'Largo tratamiento', 'Titular', 'Con goce de haberes', 'Dirección', 'Según artículo', NULL),
  ('T-20', '20', 'Licencia', 'Razones particulares', 'Razones particulares', 'Titular', 'Con goce de haberes', 'Dirección', 'Según artículo', 6),
  ('T-22', '22', 'Licencia', 'Examen', 'Examen', 'Titular', 'Con goce de haberes', 'Dirección', 'Según artículo', 10),
  ('T-25', '25', 'Licencia', 'Duelo', 'Duelo', 'Titular', 'Con goce de haberes', 'Dirección', 'Según artículo', 5);

-- ───────────── Días no laborables 2026 (ejemplo; verificá contra el calendario oficial) ─────────────
INSERT IGNORE INTO asistencia_dia_no_laborable (fecha, tipo, descripcion) VALUES
  ('2026-01-01', 'FERIADO', 'Año Nuevo'),
  ('2026-02-16', 'FERIADO', 'Carnaval'),
  ('2026-02-17', 'FERIADO', 'Carnaval'),
  ('2026-03-24', 'FERIADO', 'Día de la Memoria'),
  ('2026-04-02', 'FERIADO', 'Día del Veterano de Malvinas'),
  ('2026-04-03', 'FERIADO', 'Viernes Santo'),
  ('2026-05-01', 'FERIADO', 'Día del Trabajador'),
  ('2026-05-25', 'FERIADO', 'Revolución de Mayo'),
  ('2026-07-09', 'FERIADO', 'Día de la Independencia'),
  ('2026-12-08', 'FERIADO', 'Inmaculada Concepción'),
  ('2026-12-25', 'FERIADO', 'Navidad');

-- ───────────── Licencias otorgadas (ids 9001 a 9012) ─────────────
INSERT INTO licencia_otorgada (id, designacion_id, articulo_id, sit_rev, disp_tipo, disp_oficina, disp_numero, disp_anio, sello_regional_as, justifica, desde, hasta, observaciones) VALUES
  (9001, 9003, (SELECT id FROM licencia_articulo WHERE cod_licencia = 'T-14'), 'Interino', 'Disposición', '1452', '11', 2026, NULL, 1, '2026-05-04', '2026-06-12', 'Reposo médico'),
  (9002, 9006, (SELECT id FROM licencia_articulo WHERE cod_licencia = 'T-14'), 'Titular', 'Disposición', '1452', '12', 2026, NULL, 1, '2026-08-03', '2026-08-21', 'Gripe'),
  (9003, 9011, (SELECT id FROM licencia_articulo WHERE cod_licencia = 'T-20'), 'Interino', 'Disposición', '1452', '13', 2026, NULL, NULL, '2026-04-13', '2026-04-20', 'Trámite personal'),
  (9004, 9014, (SELECT id FROM licencia_articulo WHERE cod_licencia = 'T-22'), 'Interino', 'Disposición', '1452', '14', 2026, NULL, 1, '2026-06-01', '2026-06-05', 'Examen final'),
  (9005, 9014, (SELECT id FROM licencia_articulo WHERE cod_licencia = 'T-22'), 'Interino', 'Disposición', '1452', '15', 2026, NULL, 1, '2026-08-10', '2026-08-14', 'Examen final'),
  (9006, 9007, (SELECT id FROM licencia_articulo WHERE cod_licencia = 'T-15'), 'Interino', 'Disposición', '1452', '16', 2026, NULL, 1, '2026-09-14', NULL, 'Largo tratamiento abierto'),
  (9007, 9008, (SELECT id FROM licencia_articulo WHERE cod_licencia = 'T-22'), 'Suplente', 'Disposición', '1452', '17', 2026, NULL, 1, '2026-10-19', '2026-10-21', 'Examen'),
  (9008, 9012, (SELECT id FROM licencia_articulo WHERE cod_licencia = 'T-25'), 'Suplente', 'Disposición', '1452', '18', 2026, NULL, 1, '2026-07-13', '2026-07-17', 'Duelo familiar'),
  (9009, 9002, (SELECT id FROM licencia_articulo WHERE cod_licencia = 'T-14'), 'Titular', 'Disposición', '1452', '19', 2026, NULL, 0, '2026-03-16', '2026-03-27', 'Control médico'),
  (9010, 9005, (SELECT id FROM licencia_articulo WHERE cod_licencia = 'T-20'), 'Titular', 'Disposición', '1452', '20', 2026, NULL, NULL, '2026-09-01', '2026-09-04', 'Razones particulares'),
  (9011, 9017, (SELECT id FROM licencia_articulo WHERE cod_licencia = 'T-14'), 'Suplente', 'Disposición', '1452', '21', 2026, NULL, 1, '2026-09-21', '2026-10-16', 'Cirugía menor'),
  (9012, 9009, (SELECT id FROM licencia_articulo WHERE cod_licencia = 'T-20'), 'Titular', 'Disposición', '1452', '22', 2026, NULL, 0, '2026-10-05', '2026-10-06', 'Sin documentación');

-- ───────────── Registros de asistencia de octubre 2026 (ids automáticos; marcas P, I, PR, LIC y LT) ─────────────
INSERT IGNORE INTO asistencia_registro (designacion_id, fecha, marca_id, estado_registro, horas_inasistidas, licencia_id, observaciones, estado_justificacion, nro_formulario, fecha_recepcion, recepcionado_por_id, creado_por_id, actualizado_por_id, creado_en, actualizado_en) VALUES
  (9001, '2026-10-05', (SELECT id FROM asistencia_marca WHERE codigo = 'P'), 'VALIDADO', 0, NULL, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9001, '2026-10-06', (SELECT id FROM asistencia_marca WHERE codigo = 'P'), 'VALIDADO', 0, NULL, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9002, '2026-10-05', (SELECT id FROM asistencia_marca WHERE codigo = 'P'), 'VALIDADO', 0, NULL, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9002, '2026-10-06', (SELECT id FROM asistencia_marca WHERE codigo = 'P'), 'VALIDADO', 0, NULL, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9004, '2026-10-05', (SELECT id FROM asistencia_marca WHERE codigo = 'P'), 'VALIDADO', 0, NULL, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9004, '2026-10-06', (SELECT id FROM asistencia_marca WHERE codigo = 'P'), 'VALIDADO', 0, NULL, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9005, '2026-10-05', (SELECT id FROM asistencia_marca WHERE codigo = 'P'), 'VALIDADO', 0, NULL, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9005, '2026-10-06', (SELECT id FROM asistencia_marca WHERE codigo = 'P'), 'VALIDADO', 0, NULL, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9009, '2026-10-05', (SELECT id FROM asistencia_marca WHERE codigo = 'P'), 'VALIDADO', 0, NULL, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9009, '2026-10-06', (SELECT id FROM asistencia_marca WHERE codigo = 'P'), 'VALIDADO', 0, NULL, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9010, '2026-10-05', (SELECT id FROM asistencia_marca WHERE codigo = 'P'), 'VALIDADO', 0, NULL, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9010, '2026-10-06', (SELECT id FROM asistencia_marca WHERE codigo = 'P'), 'VALIDADO', 0, NULL, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9015, '2026-10-05', (SELECT id FROM asistencia_marca WHERE codigo = 'P'), 'VALIDADO', 0, NULL, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9015, '2026-10-06', (SELECT id FROM asistencia_marca WHERE codigo = 'P'), 'VALIDADO', 0, NULL, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9018, '2026-10-05', (SELECT id FROM asistencia_marca WHERE codigo = 'P'), 'VALIDADO', 0, NULL, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9018, '2026-10-06', (SELECT id FROM asistencia_marca WHERE codigo = 'P'), 'VALIDADO', 0, NULL, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9019, '2026-10-05', (SELECT id FROM asistencia_marca WHERE codigo = 'P'), 'VALIDADO', 0, NULL, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9019, '2026-10-06', (SELECT id FROM asistencia_marca WHERE codigo = 'P'), 'VALIDADO', 0, NULL, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9001, '2026-10-07', (SELECT id FROM asistencia_marca WHERE codigo = 'I'), 'VALIDADO', 3, NULL, 'Sin aviso', 'INJUSTIFICADA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9002, '2026-10-08', (SELECT id FROM asistencia_marca WHERE codigo = 'I'), 'VALIDADO', 3, NULL, 'Presentó certificado', 'EN_TRAMITE', 'F-2026-0101', '2026-10-10', NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9004, '2026-10-09', (SELECT id FROM asistencia_marca WHERE codigo = 'I'), 'VALIDADO', 4, NULL, 'Trámite justificado', 'JUSTIFICADA', 'F-2026-0102', '2026-10-11', NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9005, '2026-10-13', (SELECT id FROM asistencia_marca WHERE codigo = 'I'), 'VALIDADO', 3, NULL, 'Llamó tarde', 'INJUSTIFICADA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9010, '2026-10-14', (SELECT id FROM asistencia_marca WHERE codigo = 'I'), 'VALIDADO', 2, NULL, 'Control médico', 'EN_TRAMITE', 'F-2026-0103', '2026-10-16', NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9015, '2026-10-15', (SELECT id FROM asistencia_marca WHERE codigo = 'I'), 'VALIDADO', 4, NULL, 'Sin aviso', 'INJUSTIFICADA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9018, '2026-10-16', (SELECT id FROM asistencia_marca WHERE codigo = 'I'), 'VALIDADO', 3, NULL, 'Duelo', 'JUSTIFICADA', 'F-2026-0104', '2026-10-18', NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9009, '2026-10-19', (SELECT id FROM asistencia_marca WHERE codigo = 'I'), 'VALIDADO', 3, NULL, 'Sin aviso', 'INJUSTIFICADA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9019, '2026-10-20', (SELECT id FROM asistencia_marca WHERE codigo = 'I'), 'BORRADOR', 2, NULL, 'Sin aviso', 'INJUSTIFICADA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9002, '2026-10-22', (SELECT id FROM asistencia_marca WHERE codigo = 'PR'), 'VALIDADO', 1, NULL, 'Se retiró antes', 'INJUSTIFICADA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9010, '2026-10-23', (SELECT id FROM asistencia_marca WHERE codigo = 'PR'), 'VALIDADO', 1, NULL, 'Retiro anticipado', 'INJUSTIFICADA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9008, '2026-10-19', (SELECT id FROM asistencia_marca WHERE codigo = 'LIC'), 'VALIDADO', 3, 9007, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9008, '2026-10-20', (SELECT id FROM asistencia_marca WHERE codigo = 'LIC'), 'VALIDADO', 3, 9007, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9008, '2026-10-21', (SELECT id FROM asistencia_marca WHERE codigo = 'LIC'), 'VALIDADO', 3, 9007, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9007, '2026-10-05', (SELECT id FROM asistencia_marca WHERE codigo = 'LT'), 'VALIDADO', 4, 9006, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9007, '2026-10-06', (SELECT id FROM asistencia_marca WHERE codigo = 'LT'), 'VALIDADO', 4, 9006, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (9007, '2026-10-07', (SELECT id FROM asistencia_marca WHERE codigo = 'LT'), 'VALIDADO', 4, 9006, '', 'NO_APLICA', '', NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);

-- ───────────── Usuarios del sistema (contraseña de todos: Prueba2026!) ─────────────
INSERT IGNORE INTO auth_user (password, last_login, is_superuser, username, first_name, last_name, email, is_staff, is_active, date_joined) VALUES
  ('pbkdf2_sha256$1500000$semillaprueba$eWpl3LGlNzFkmFNPBMMNntblTlaO8uB4U+bsQTj6SoE=', NULL, 0, 'bedelia1', 'Ana', 'Bedel', 'bedelia1@ejemplo.test', 0, 1, '2026-10-01 09:00:00'),
  ('pbkdf2_sha256$1500000$semillaprueba$eWpl3LGlNzFkmFNPBMMNntblTlaO8uB4U+bsQTj6SoE=', NULL, 0, 'bedelia2', 'Julia', 'Ríos', 'bedelia2@ejemplo.test', 0, 1, '2026-10-01 09:00:00'),
  ('pbkdf2_sha256$1500000$semillaprueba$eWpl3LGlNzFkmFNPBMMNntblTlaO8uB4U+bsQTj6SoE=', NULL, 0, 'bedelia3', 'Marcos', 'Paz', 'bedelia3@ejemplo.test', 0, 1, '2026-10-01 09:00:00'),
  ('pbkdf2_sha256$1500000$semillaprueba$eWpl3LGlNzFkmFNPBMMNntblTlaO8uB4U+bsQTj6SoE=', NULL, 0, 'secretaria1', 'Laura', 'Medina', 'secretaria1@ejemplo.test', 0, 1, '2026-10-01 09:00:00'),
  ('pbkdf2_sha256$1500000$semillaprueba$eWpl3LGlNzFkmFNPBMMNntblTlaO8uB4U+bsQTj6SoE=', NULL, 0, 'secretaria2', 'Hugo', 'Vega', 'secretaria2@ejemplo.test', 0, 1, '2026-10-01 09:00:00'),
  ('pbkdf2_sha256$1500000$semillaprueba$eWpl3LGlNzFkmFNPBMMNntblTlaO8uB4U+bsQTj6SoE=', NULL, 0, 'secretaria3', 'Rita', 'Luna', 'secretaria3@ejemplo.test', 0, 1, '2026-10-01 09:00:00'),
  ('pbkdf2_sha256$1500000$semillaprueba$eWpl3LGlNzFkmFNPBMMNntblTlaO8uB4U+bsQTj6SoE=', NULL, 0, 'subsecretaria1', 'Elena', 'Ramos', 'subsecretaria1@ejemplo.test', 0, 1, '2026-10-01 09:00:00'),
  ('pbkdf2_sha256$1500000$semillaprueba$eWpl3LGlNzFkmFNPBMMNntblTlaO8uB4U+bsQTj6SoE=', NULL, 0, 'subsecretaria2', 'Raúl', 'Castro', 'subsecretaria2@ejemplo.test', 0, 1, '2026-10-01 09:00:00'),
  ('pbkdf2_sha256$1500000$semillaprueba$eWpl3LGlNzFkmFNPBMMNntblTlaO8uB4U+bsQTj6SoE=', NULL, 0, 'subsecretaria3', 'Inés', 'Molina', 'subsecretaria3@ejemplo.test', 0, 1, '2026-10-01 09:00:00');

-- Asigna el rol (grupo) de cada usuario. Los grupos los crea la migración.
INSERT IGNORE INTO auth_user_groups (user_id, group_id)
SELECT u.id, gr.id FROM auth_user u JOIN auth_group gr ON gr.name = 'Bedelía'
WHERE u.username IN ('bedelia1', 'bedelia2', 'bedelia3');
INSERT IGNORE INTO auth_user_groups (user_id, group_id)
SELECT u.id, gr.id FROM auth_user u JOIN auth_group gr ON gr.name = 'Secretaría'
WHERE u.username IN ('secretaria1', 'secretaria2', 'secretaria3');
INSERT IGNORE INTO auth_user_groups (user_id, group_id)
SELECT u.id, gr.id FROM auth_user u JOIN auth_group gr ON gr.name = 'Subsecretaría'
WHERE u.username IN ('subsecretaria1', 'subsecretaria2', 'subsecretaria3');

COMMIT;

-- =============================================================================
-- LIMPIEZA (descomentá para quitar los datos de prueba; las carreras, materias,
-- cargos, artículos y feriados quedan porque pueden ser datos reales)
-- =============================================================================
-- DELETE FROM asistencia_registro WHERE designacion_id BETWEEN 9001 AND 9022;
-- DELETE FROM licencia_otorgada WHERE id BETWEEN 9001 AND 9012;
-- DELETE FROM personal_horario WHERE designacion_id BETWEEN 9001 AND 9022;
-- DELETE FROM personal_historial_designacion WHERE designacion_id BETWEEN 9001 AND 9022;
-- DELETE FROM personal_designacion WHERE id BETWEEN 9001 AND 9022;
-- DELETE FROM personal_persona WHERE dni BETWEEN '99000001' AND '99000020';
-- DELETE FROM auth_user_groups WHERE user_id IN (SELECT id FROM auth_user WHERE username REGEXP '^(bedelia|secretaria|subsecretaria)[0-9]$');
-- DELETE FROM auth_user WHERE username REGEXP '^(bedelia|secretaria|subsecretaria)[0-9]$';
