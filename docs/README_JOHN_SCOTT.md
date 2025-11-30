# Agente John Scott - GHOSTS NPC

## Descripción
John Scott es un **Senior Developer** simulado mediante GHOSTS Framework que ejecuta consultas PostgreSQL automáticas sobre la base de datos `labdb`.

## Perfil del Agente
- **Nombre**: John Scott
- **Rol**: Senior Developer
- **Usuario DB**: john_scott (con role: senior_developer_role)
- **Descripción**: Desarrollador senior con experiencia en arquitectura de bases de datos y optimización de queries. Especializado en análisis de datos de recursos humanos y reportes de empleados.

## Arquitectura de Conexión
```
GHOSTS Driver (lab_ghosts_driver)
    |
    | SSH (clave privada: id_rsa)
    v
Compromised Machine (lab_compromised - 172.30.0.10)
    |
    | PostgreSQL Client (psql)
    v
Database Server (lab_server - 172.31.0.10:5432)
    Database: labdb
    User: john_scott
```

## Timeline de Actividades

### Ciclo de Trabajo (Loop infinito)

1. **Inicio de sesión** (Delay: 5s antes, 10s después)
   - Mensaje: `[JOHN_SCOTT] Senior Developer starting work session`

2. **Query 1: Verificación de versión** (Delay: 3s antes, 20s después)
   ```sql
   SELECT current_database(), current_user, version();
   ```
   **Resultado esperado**: PostgreSQL 14.19, usuario senior_developer_role

3. **Query 2: Empleados de Development** (Delay: 5s antes, 25s después)
   ```sql
   SELECT e.first_name, e.last_name, e.hire_date, d.dept_name 
   FROM employee e 
   JOIN department_employee de ON e.id = de.employee_id 
   JOIN department d ON de.department_id = d.id 
   WHERE d.dept_name = $$Development$$ 
   ORDER BY e.hire_date DESC 
   LIMIT 10;
   ```
   **Resultado esperado**: 10 empleados del departamento Development ordenados por fecha de contratación

4. **Query 3: Conteo de empleados por departamento** (Delay: 5s antes, 30s después)
   ```sql
   SELECT d.dept_name, COUNT(de.employee_id) as employee_count 
   FROM department d 
   JOIN department_employee de ON d.id = de.department_id 
   GROUP BY d.dept_name 
   ORDER BY employee_count DESC;
   ```
   **Resultado esperado**: 9 departamentos con sus conteos (Development: 85,707 empleados)

5. **Query 4: Empleados Senior mejor pagados** (Delay: 5s antes, 35s después)
   ```sql
   SELECT e.id, e.first_name, e.last_name, t.title, s.amount as salary 
   FROM employee e 
   JOIN title t ON e.id = t.employee_id 
   JOIN salary s ON e.id = s.employee_id 
   WHERE t.title LIKE $$%Senior%$$ AND s.to_date = $$9999-01-01$$ 
   ORDER BY s.amount DESC 
   LIMIT 15;
   ```
   **Resultado esperado**: 15 empleados Senior Staff ordenados por salario (máximo: $158,220)

6. **Fin de ciclo** (Delay: 5s antes, 60s después)
   - Mensaje: `[JOHN_SCOTT] Work session cycle completed`

**Tiempo total del ciclo**: ~2 minutos

## Testing

### Script de Testing: `test_john_scott.sh`

```bash
./test_john_scott.sh <comando>
```

### Comandos disponibles:

- `rebuild`: Reconstruir imagen Docker
- `start`: Iniciar agente
- `stop`: Detener agente
- `restart`: Reiniciar agente
- `logs [n]`: Ver últimos N logs (default: 50)
- `status`: Ver estado del agente
- `check-bash`: Verificar thread Bash inicializado
- `check-ssh`: Verificar ejecución SSH
- `check-db`: Verificar consultas PostgreSQL
- `activity`: Ver actividad reciente
- `db-results`: Ver resultados de queries
- `full-test`: Test completo (rebuild + start + verificación)

### Ejemplo de uso:

```bash
# Test completo
./test_john_scott.sh full-test

# Ver resultados de queries
./test_john_scott.sh db-results

# Ver estado
./test_john_scott.sh status
```

## Detalles Técnicos

### Escaping de Strings SQL
Las queries usan **PostgreSQL Dollar Quoting** (`$$`) para evitar problemas de escaping multi-capa:

```
JSON → Bash → SSH → Remote Bash → psql → PostgreSQL
```

Ejemplo: `WHERE dept_name = $$Development$$` se convierte en `WHERE dept_name = 'Development'` en PostgreSQL.

### Archivos de Configuración

- **Timeline**: `/images/ghosts_driver/timeline_john_scott.json`
- **Application Config**: `/images/ghosts_driver/application.json`
- **SSH Key**: `/images/ghosts_driver/id_rsa`
- **Testing Script**: `/images/ghosts_driver/test_john_scott.sh`
- **Architecture Docs**: `/images/ghosts_driver/ARCHITECTURE.md`

### Logs GHOSTS

Los logs se categorizan por nivel:
- **TRACE**: Comandos ejecutados línea por línea
- **INFO/TIMELINE**: Resultados de ejecución con salida completa
- **DEBUG**: Información de WorkingHours y estado interno

Ejemplo de log exitoso:
```json
{"Handler":"Command","Command":"ssh ... psql ...","Result":"... 10 rows ..."}
```

## Verificación de Funcionamiento

### Indicadores de éxito:
1. ✅ Thread Bash inicializado: `Attempting new thread for: Bash`
2. ✅ SSH commands ejecutados: conteo > 0
3. ✅ Queries PostgreSQL ejecutadas: conteo > 0
4. ✅ Resultados con datos (no errores): `(N rows)` en output

### Errores comunes resueltos:
- ❌ `ERROR: column "development" does not exist` → **RESUELTO** con dollar quoting
- ❌ `ERROR: syntax error at or near "%"` → **RESUELTO** con dollar quoting
- ❌ Handler mismatch (Word vs Bash) → **RESUELTO** con paths correctos en Dockerfile

## Próximos Pasos (LLM Integration)

El agente está listo para integración con LLM para generar queries dinámicas:

```python
# Variables de entorno disponibles
OPENAI_API_KEY=YOUR_API_KEY
OPENAI_BASE_URL=https://chat.ai.e-infra.cz/api/
LLM_MODEL=qwen3-coder
```

Implementación sugerida:
1. Crear wrapper Python que lee logs de GHOSTS
2. Enviar contexto al LLM (esquema DB + historial)
3. LLM genera nueva query SQL
4. Wrapper actualiza timeline.json dinámicamente
5. GHOSTS ejecuta nueva query automáticamente

## Conclusión

El agente John Scott está **completamente funcional** ejecutando 4 queries SQL diferentes en ciclos automáticos sobre la base de datos labdb, simulando el comportamiento de un desarrollador senior consultando información de empleados.

**Status**: ✅ PRODUCTION READY
