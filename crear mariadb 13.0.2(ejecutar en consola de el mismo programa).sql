CREATE DATABASE asistencia CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'asistencia'@'localhost' IDENTIFIED BY 'una_clave';
GRANT ALL PRIVILEGES ON *.* TO 'asistencia'@'localhost';
FLUSH PRIVILEGES;
SHOW VARIABLES LIKE 'port';