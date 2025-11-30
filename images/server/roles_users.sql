-- PostgreSQL version of roles_users.sql
-- 1. Crear el ROL de Desarrollador
CREATE ROLE senior_developer_role;

-- 2. Asignar permisos amplios (DDL y DML) en la base 'labdb'

-- Permisos de Datos (DML): Para leer, crear y borrar datos de prueba
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO senior_developer_role;
GRANT SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO senior_developer_role;

-- Permisos futuros: Para tablas que se creen después
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO senior_developer_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, UPDATE ON SEQUENCES TO senior_developer_role;

-- Permisos de Estructura (DDL): Lo que lo hace un "Desarrollador"
GRANT CREATE ON SCHEMA public TO senior_developer_role;

-- Permisos de base de datos
GRANT CONNECT ON DATABASE labdb TO senior_developer_role;
GRANT USAGE ON SCHEMA public TO senior_developer_role;

-- 3. Crear al USUARIO Desarrollador con LOGIN
-- PostgreSQL no usa el '@host' syntax como MySQL
CREATE USER john_scott WITH PASSWORD 'john_scott' LOGIN;

-- 4. Asignar el rol al usuario
GRANT senior_developer_role TO john_scott;

-- 5. Establecer permisos por defecto
ALTER ROLE john_scott SET ROLE senior_developer_role;
