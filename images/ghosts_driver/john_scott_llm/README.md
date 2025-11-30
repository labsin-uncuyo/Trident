# John Scott LLM - NPC con Integración de LLM

## Descripción

`john_scott_llm` es un agente NPC (Non-Player Character) para GHOSTS que utiliza un Large Language Model (LLM) para generar consultas SQL dinámicamente. A diferencia de `john_scott_dummy` que usa queries hardcodeadas, este agente genera comportamiento adaptativo usando IA.

## Arquitectura de Integración LLM + GHOSTS

### Flujo de Trabajo

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Inicio del Contenedor (ghosts_driver)                    │
│    - Lee JOHN_SCOTT_MODE desde variables de entorno         │
│    - Si MODE=llm → ejecuta generate_timeline.sh             │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. Generación de Timeline (generate_timeline_llm.py)        │
│    - Lee configuración LLM desde env vars                   │
│    - Define tareas en lenguaje natural                      │
│    - Por cada tarea: llama al LLM para generar SQL          │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. LLM API Call (OpenAI-compatible)                         │
│    Input: "Check all employees in Engineering department"   │
│    Context: Schema de la base de datos (tables, columns)    │
│    Output: "SELECT * FROM employees WHERE department=       │
│            'Engineering' LIMIT 10;"                          │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. Construcción del Timeline JSON                           │
│    - Cada query SQL → evento en el timeline                 │
│    - Incluye comandos SSH con queries generadas             │
│    - Guarda: timeline_john_scott_llm.json                   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. GHOSTS Client Ejecuta Timeline                           │
│    - Lee timeline.json                                       │
│    - Ejecuta comandos SSH a 172.30.0.10 (compromised)       │
│    - Cada comando ejecuta psql con la query generada        │
│    - Loop continuo con delays configurados                  │
└─────────────────────────────────────────────────────────────┘
```

### Componentes Clave

#### 1. **generate_timeline_llm.py**
Script Python que genera el timeline dinámicamente usando LLM.

**Responsabilidades:**
- Conectar con API de LLM (OpenAI-compatible)
- Enviar prompts con contexto del schema de la base de datos
- Generar queries SQL basadas en descripciones de tareas
- Construir timeline JSON para GHOSTS
- Manejar fallbacks si el LLM falla

**Configuración LLM:**
```python
LLM_API_KEY = os.getenv('OPENAI_API_KEY')
LLM_BASE_URL = os.getenv('OPENAI_BASE_URL').rstrip('/')  # Elimina trailing slash
LLM_MODEL = os.getenv('LLM_MODEL', 'qwen3-coder')
LLM_TEMPERATURE = float(os.getenv('LLM_TEMPERATURE', '0.7'))
```

**Prompt del Sistema:**
```python
SYSTEM_PROMPT = f"""You are a PostgreSQL query generator for John Scott, a Senior Developer.

{DATABASE_SCHEMA}  # Incluye estructura completa de tablas

Generate ONLY the PostgreSQL query without any explanation, markdown formatting, or additional text.
The query must be a valid PostgreSQL statement that can be executed directly.
Vary the queries - include SELECT, JOIN, GROUP BY, COUNT, AVG, SUM operations.
Keep queries realistic for a developer's daily work.
Respond with ONLY the SQL query, nothing else."""
```

#### 2. **Conexión SSH Hardcodeada**
Como solicitaste, la conexión SSH está fija en el código:

```python
SSH_TARGET = "labuser@172.30.0.10"
SSH_KEY = "/root/.ssh/id_rsa"
SSH_OPTIONS = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
```

#### 3. **Tareas en Lenguaje Natural**
Las tareas se definen como descripciones, no como SQL:

```python
tasks = [
    "Check all employees in the Engineering department",
    "Find the average salary by department",
    "List all active projects with their team sizes",
    "Get recent hires from the last year",
    "Show department budgets and managers",
    "Find employees working on multiple projects",
    "Calculate total project hours by employee",
    "List departments with more than 10 employees"
]
```

El LLM convierte cada tarea en una query SQL apropiada.

#### 4. **Integration con GHOSTS**
El timeline generado tiene el formato estándar de GHOSTS:

```json
{
  "Id": "d531df3a-c946-4a53-beac-57d70c97d799",
  "Status": "Active",
  "TimeLineHandlers": [{
    "HandlerType": "Command",
    "Loop": true,
    "TimeLineEvents": [
      {
        "Command": "ssh -i /root/.ssh/id_rsa labuser@172.30.0.10 \"psql -h 172.30.0.3 -U laboratorio -d employees -c \\\"SELECT * FROM employees WHERE department='Engineering'\\\"\"",
        "DelayAfter": 30000,
        "DelayBefore": 15000
      }
    ]
  }]
}
```

## Variables de Entorno

Definidas en `.env` y pasadas por `docker-compose.yml`:

```bash
# Proveedor LLM (e-INFRA CZ o compatible OpenAI)
OPENAI_API_KEY=YOUR_API_KEY
OPENAI_BASE_URL=https://chat.ai.e-infra.cz/api
LLM_MODEL=qwen3-coder
LLM_TEMPERATURE=0.7

# Modo de operación (dummy o llm)
JOHN_SCOTT_MODE=llm  # Se define al ejecutar docker compose
```

## Uso

### 1. Levantar en Modo LLM

```bash
# Reconstruir imagen con los cambios
docker compose build ghosts_driver

# Levantar en modo LLM
JOHN_SCOTT_MODE=llm docker compose up -d ghosts_driver
```

### 2. Verificar Timeline Generado

```bash
# Ver logs de generación
docker logs lab_ghosts_driver --tail 50

# Debería mostrar:
# [INFO] Starting LLM-powered timeline generation for John Scott
# [INFO] Using LLM: qwen3-coder at https://chat.ai.e-infra.cz/api
# [INFO] Generating query 1/8: Check all employees in Engineering department
# [INFO] Generated query: SELECT * FROM employees WHERE department='Engineering' LIMIT 10;
# [SUCCESS] Timeline generated successfully
```

### 3. Ver Timeline Generado

```bash
# Copiar timeline desde el contenedor
docker cp lab_ghosts_driver:/opt/john_scott_llm/timeline_john_scott_llm.json ./timeline_llm.json

# Ver contenido
cat timeline_llm.json | jq '.TimeLineHandlers[0].TimeLineEvents[] | .Command' | head -20
```

### 4. Verificar Ejecución en Tiempo Real

```bash
# Seguir logs en vivo
docker logs lab_ghosts_driver -f

# Debería mostrar comandos SSH ejecutándose:
# 2025-11-27 14:00:01|INFO|TIMELINE|Command: ssh labuser@172.30.0.10 "PGPASSWORD=... psql -c \"SELECT AVG(salary) FROM employees GROUP BY department;\""
# Result: department | avg
#         Engineering | 95000.00
#         Marketing   | 75000.00
```

### 5. Conectarse al Contenedor para Debug

```bash
# Entrar al contenedor
docker exec -it lab_ghosts_driver bash

# Ver archivos generados
ls -la /opt/john_scott_llm/
cat /opt/john_scott_llm/timeline_john_scott_llm.json

# Regenerar timeline manualmente
cd /opt/john_scott_llm
python3 generate_timeline_llm.py

# Ver logs de GHOSTS
tail -f /opt/ghosts/bin/logs/*.log
```

### 6. Verificar Queries en la Base de Datos

```bash
# Conectarse a la máquina comprometida
ssh -i images/ghosts_driver/john_scott_dummy/id_rsa labuser@localhost -p 2223

# Ver historial de comandos ejecutados por john_scott_llm
history | grep "JOHN_SCOTT_LLM"

# Conectarse directamente a la base de datos
PGPASSWORD=scotty@1 psql -h 172.30.0.3 -U laboratorio -d employees

# Ver tablas disponibles
\dt

# Ejecutar query de ejemplo
SELECT * FROM employees LIMIT 5;
```

## Comparación: Dummy vs LLM

### Similitudes (Lo que comparten)

Ambos modos utilizan la **misma infraestructura base**:

✅ **Mismo `application.json`** - Configuración de GHOSTS idéntica
✅ **Mismas credenciales SSH** - Usan `id_rsa` / `id_rsa.pub` compartidas
✅ **Mismo target SSH** - Ambos se conectan a `labuser@172.30.0.10` (compromised)
✅ **Misma base de datos** - PostgreSQL en `172.30.0.3:5432` (employees)
✅ **Mismo usuario DB** - `laboratorio` con contraseña `scotty@1`
✅ **Mismo formato timeline** - JSON compatible con GHOSTS Client Universal
✅ **Mismo HandlerType** - Ambos usan `Command` con bash/ssh
✅ **Mismo contenedor** - Ejecutan en el mismo `lab/ghosts_driver:latest`
✅ **Mismo entrypoint** - `entrypoint.sh` detecta el modo via `JOHN_SCOTT_MODE`

**Directorio compartido:**
```
images/ghosts_driver/
├── application.json          ← Compartido por ambos
├── entrypoint.sh             ← Detecta modo (dummy/llm)
├── john_scott_dummy/
│   ├── id_rsa                ← Copiado a john_scott_llm/
│   ├── id_rsa.pub            ← Copiado a john_scott_llm/
│   └── timeline.json         ← Timeline estático
└── john_scott_llm/
    ├── id_rsa                ← Copia del dummy
    ├── id_rsa.pub            ← Copia del dummy
    ├── generate_timeline_llm.py  ← Generador dinámico
    └── timeline_john_scott_llm.json  ← Generado en runtime
```

### Diferencias Clave

| Aspecto | john_scott_dummy | john_scott_llm |
|---------|------------------|----------------|
| **🎯 Generación de Queries** | 13 queries SQL **hardcodeadas** en `timeline.json` | Queries **generadas dinámicamente** por LLM al inicio |
| **🔄 Variabilidad** | Mismo comportamiento cada vez | Comportamiento **adaptativo** - queries diferentes en cada ejecución |
| **📝 Definición de Tareas** | SQL directo en JSON | **Descripciones en lenguaje natural** (ej: "Find average salary by department") |
| **🔌 Dependencias Externas** | Ninguna - funciona offline | Requiere **API LLM** (OpenAI-compatible) |
| **⚙️ Configuración** | Timeline estático pre-generado | Timeline generado **en tiempo de arranque** |
| **🚀 Tiempo de Inicio** | Instantáneo (~2 segundos) | +20-30 segundos (llamadas al LLM) |
| **📊 Complejidad Queries** | Queries fijas simples/intermedias | Queries **variadas y contextuales** generadas por IA |
| **🛡️ Fallback** | N/A - siempre funciona | Queries simples si LLM falla |
| **💰 Costo** | Gratis | Depende del proveedor LLM (gratis con e-INFRA CZ) |
| **🔧 Mantenimiento** | Editar JSON manualmente | Editar **descripciones en Python** |

### Cuándo Usar Cada Uno

**Usa `john_scott_dummy` cuando:**
- ✅ Necesitas comportamiento predecible y consistente
- ✅ No tienes acceso a API de LLM
- ✅ Quieres arranque rápido sin dependencias externas
- ✅ Estás en entorno offline/air-gapped
- ✅ El timeline está bien definido y no necesita cambios

**Usa `john_scott_llm` cuando:**
- ✅ Quieres comportamiento más realista y variable
- ✅ Tienes acceso a LLM API (OpenAI, e-INFRA CZ, etc.)
- ✅ Necesitas generar queries complejas sin escribir SQL
- ✅ Quieres simular un desarrollador real que adapta sus queries
- ✅ Estás investigando comportamiento adaptativo de NPCs

## Testing Completo

### Test 1: Verificar Modo de Operación

```bash
# Ver qué modo está activo
docker exec lab_ghosts_driver bash -c 'echo "Mode: $JOHN_SCOTT_MODE"'
```

### Test 2: Verificar Conectividad LLM

```bash
# Test manual del API
curl -X POST "https://chat.ai.e-infra.cz/api/v1/chat/completions" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-coder",
    "messages": [
      {"role": "user", "content": "Generate a SQL query to count all employees"}
    ],
    "temperature": 0.7
  }'
```

### Test 3: Regenerar Timeline con Diferentes Temperaturas

```bash
# Temperatura baja = queries más determinísticas
docker exec -e LLM_TEMPERATURE=0.2 lab_ghosts_driver bash -c 'cd /opt/john_scott_llm && python3 generate_timeline_llm.py'

# Temperatura alta = queries más creativas
docker exec -e LLM_TEMPERATURE=1.0 lab_ghosts_driver bash -c 'cd /opt/john_scott_llm && python3 generate_timeline_llm.py'

# Comparar diferencias
docker cp lab_ghosts_driver:/opt/john_scott_llm/timeline_john_scott_llm.json ./timeline_temp_test.json
```

### Test 4: Verificar Fallback

```bash
# Simular fallo de LLM (API key inválida)
docker exec -e OPENAI_API_KEY=invalid lab_ghosts_driver bash -c 'cd /opt/john_scott_llm && python3 generate_timeline_llm.py'

# Debería usar queries fallback simples
docker logs lab_ghosts_driver --tail 20 | grep "fallback"
```

### Test 5: Monitoreo de Actividad

```bash
# Ver actividad en tiempo real
watch -n 2 'docker logs lab_ghosts_driver --tail 5'

# O usar tmux/screen para múltiples vistas:
# Panel 1: logs de GHOSTS
docker logs lab_ghosts_driver -f

# Panel 2: logs del servidor comprometido
docker logs lab_compromised -f

# Panel 3: queries en la base de datos
docker exec -it lab_server bash -c 'tail -f /var/log/postgresql/*.log'
```

## Troubleshooting

### Problema: "405 Method Not Allowed"
**Causa:** URL del API incorrecta (doble barra `/api//chat`)
**Solución:** Verificar que `OPENAI_BASE_URL` no termine en `/`

```bash
# En .env debe ser:
OPENAI_BASE_URL=https://chat.ai.e-infra.cz/api
# NO:
OPENAI_BASE_URL=https://chat.ai.e-infra.cz/api/
```

### Problema: Timeline no se genera
**Causa:** Error en llamada al LLM o permisos
**Debug:**
```bash
docker exec -it lab_ghosts_driver bash
cd /opt/john_scott_llm
python3 generate_timeline_llm.py
# Ver error completo
```

### Problema: Queries SQL inválidas
**Causa:** LLM genera SQL mal formateado
**Solución:** Ajustar temperatura o mejorar el prompt del sistema

### Problema: Conexión SSH falla
**Causa:** Clave SSH incorrecta o máquina comprometida no disponible
**Debug:**
```bash
docker exec lab_ghosts_driver ssh -i /root/.ssh/id_rsa labuser@172.30.0.10 "echo test"
```

## Archivos Importantes

```
john_scott_llm/
├── generate_timeline_llm.py    # Script principal de generación
├── generate_timeline.sh        # Wrapper bash para ejecutar el script
├── requirements.txt            # Dependencias Python (requests)
├── id_rsa                      # Clave SSH privada (copiada de dummy)
├── id_rsa.pub                  # Clave SSH pública
└── timeline_john_scott_llm.json  # Timeline generado (creado en runtime)
```

## Ventajas del Enfoque LLM

1. **Comportamiento Adaptativo:** Cada ejecución puede generar queries ligeramente diferentes
2. **Mantenibilidad:** Cambiar el comportamiento editando descripciones en lenguaje natural
3. **Realismo:** Las queries varían como lo haría un desarrollador real
4. **Extensibilidad:** Fácil agregar nuevas tareas sin escribir SQL
5. **Testing:** El LLM puede generar queries de prueba automáticamente

## Próximos Pasos

- Agregar más tareas de desarrollo realistas
- Integrar análisis de datos con pandas/matplotlib
- Implementar respuestas adaptativas basadas en resultados de queries
- Logging avanzado de actividad del NPC
- Integración con GHOSTS Shadows para comportamiento más complejo
