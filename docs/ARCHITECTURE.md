# Arquitectura GHOSTS en el Proyecto Trident

## Índice
- [Descripción General](#descripción-general)
- [Arquitectura del Sistema](#arquitectura-del-sistema)
- [Integración de GHOSTS](#integración-de-ghosts)
- [Flujo de Interacción](#flujo-de-interacción)
- [Configuración Técnica](#configuración-técnica)
- [Resolución de Problemas](#resolución-de-problemas)

---

## Descripción General

**GHOSTS** (GitHub Hosted Open Source Threat Simulator) es un framework de simulación de actividad humana diseñado para generar tráfico y comportamiento realista en entornos de ciberseguridad. En este proyecto, GHOSTS se utiliza para simular un atacante que ha comprometido una máquina (`lab_compromised`) y ejecuta comandos remotos de forma automatizada.

### Propósito en Trident
- **Simulación de amenazas**: Genera actividad de ataque realista para entrenar sistemas de detección
- **Automatización**: Ejecuta comandos SSH de forma programada hacia la máquina comprometida
- **Generación de tráfico**: Crea logs y tráfico de red para análisis por parte de SLIPS defender

---

## Arquitectura del Sistema

### Componentes Principales

```
┌─────────────────────────────────────────────────────────────────┐
│                        Docker Network                           │
│                                                                 │
│  ┌──────────────────┐        SSH (22)        ┌──────────────┐  │
│  │                  │ ──────────────────────> │              │  │
│  │  lab_ghosts_     │   172.30.0.10          │    lab_      │  │
│  │     driver       │                        │ compromised  │  │
│  │                  │ <────────────────────── │              │  │
│  │ (GHOSTS Client)  │   Commands/Results     │  (Target)    │  │
│  └──────────────────┘                        └──────────────┘  │
│         │                                            │          │
│         │                                            │          │
│         └────────────────────┬───────────────────────┘          │
│                              │                                  │
│                              ▼                                  │
│                     ┌─────────────────┐                         │
│                     │  lab_slips_     │                         │
│                     │    defender     │                         │
│                     │  (Monitoring)   │                         │
│                     └─────────────────┘                         │
└─────────────────────────────────────────────────────────────────┘
```

### Contenedores Docker

1. **`lab_ghosts_driver`** (172.30.0.20)
   - Ejecuta GHOSTS Client Universal
   - Simula comportamiento de atacante
   - Envía comandos SSH automatizados

2. **`lab_compromised`** (172.30.0.10)
   - Máquina objetivo comprometida
   - Acepta conexiones SSH con clave pública
   - Ejecuta comandos recibidos del driver

3. **`lab_slips_defender`**
   - Monitorea tráfico de red
   - Detecta actividad sospechosa
   - Genera alertas de seguridad

---

## Integración de GHOSTS

### 1. Compilación y Construcción

El Dockerfile construye GHOSTS desde el código fuente:

```dockerfile
# Instalar .NET SDK 9.0
RUN wget https://dot.net/v1/dotnet-install.sh -O dotnet-install.sh \
    && chmod +x dotnet-install.sh \
    && ./dotnet-install.sh --channel 9.0 --install-dir /usr/share/dotnet

# Copiar y compilar GHOSTS Client Universal para Linux ARM64
COPY GHOSTS /opt/ghosts_repo
WORKDIR /opt/ghosts_repo/src/Ghosts.Client.Universal
RUN dotnet publish -c Release -r linux-arm64 --self-contained true -o /opt/ghosts/bin
```

### 2. Estructura de Directorios

```
/opt/ghosts/
├── bin/
│   ├── Ghosts.Client.Universal          # Ejecutable principal
│   └── config/
│       ├── application.json             # Configuración del cliente
│       └── timeline.json                # Timeline de eventos
├── instance/
│   └── timeline/
│       ├── in/                          # Timelines entrantes
│       └── out/                         # Timelines salientes
└── logs/                                # Archivos de log
```

### 3. Configuración SSH

```bash
# Configuración de llave privada SSH
COPY images/ghosts_driver/id_rsa /root/.ssh/id_rsa
RUN chmod 600 /root/.ssh/id_rsa && chmod 700 /root/.ssh
```

La llave pública correspondiente está instalada en `lab_compromised` para permitir autenticación sin contraseña.

---

## Flujo de Interacción

### Fase 1: Inicialización

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Contenedor lab_ghosts_driver inicia                      │
│    ↓                                                         │
│ 2. entrypoint.sh verifica conectividad                      │
│    - Ping a 172.30.0.10                                     │
│    - Test de conexión SSH                                   │
│    ↓                                                         │
│ 3. Inicia GHOSTS Client Universal                          │
│    - Carga application.json                                 │
│    - Carga timeline.json                                    │
│    - Inicializa handlers                                    │
└─────────────────────────────────────────────────────────────┘
```

**Logs de inicialización:**
```
=== GHOSTS Driver Starting ===
✓ SSH private key configured
✓ Compromised machine is reachable
✓ SSH connection test passed
Starting GHOSTS client...
GHOSTS (Ghosts.Client.Universal:8.0.0.0 [8.5.1.0]) running in production mode.
```

### Fase 2: Carga del Timeline

```
┌─────────────────────────────────────────────────────────────┐
│ Timeline cargado con HandlerType: "Bash"                    │
│    ↓                                                         │
│ Orchestrator.ThreadLaunch()                                 │
│    ↓                                                         │
│ RunHandler(HandlerType.Bash, timeline, handler, token)     │
│    ↓                                                         │
│ Instancia la clase Bash.cs                                 │
│    ↓                                                         │
│ BaseHandler.Run() → RunOnce() en bucle (Loop: true)       │
└─────────────────────────────────────────────────────────────┘
```

**Logs del handler:**
```
2025-11-26 21:41:25|TRACE|Attempting new thread for: Bash
2025-11-26 21:41:25|DEBUG|For Bash: Current UTC: ... On: 00:00:00 Off: 23:59:00
```

### Fase 3: Ejecución de Comandos SSH

El timeline define una secuencia de comandos que se ejecutan cíclicamente:

```json
{
  "Status": "Run",
  "TimeLineHandlers": [
    {
      "HandlerType": "Bash",
      "Loop": true,
      "TimeLineEvents": [
        {
          "Command": "ssh ... labuser@172.30.0.10 \"echo '[GHOSTS-TEST] ...'\"",
          "DelayBefore": 10000,
          "DelayAfter": 30000
        },
        {
          "Command": "ssh ... labuser@172.30.0.10 \"whoami && hostname\"",
          "DelayBefore": 5000,
          "DelayAfter": 30000
        },
        {
          "Command": "ssh ... labuser@172.30.0.10 \"ping -c 2 172.31.0.10\"",
          "DelayBefore": 5000,
          "DelayAfter": 45000
        }
      ]
    }
  ]
}
```

#### Flujo de Ejecución de un Comando

```
┌──────────────────────────────────────────────────────────────┐
│ 1. WorkingHours.Is() - Verifica horario permitido           │
│    ↓                                                          │
│ 2. Thread.Sleep(DelayBefore) - Espera inicial               │
│    ↓                                                          │
│ 3. ProcessCommand() en Bash.cs                              │
│    ├─> Crea Process con FileName: "bash"                    │
│    ├─> Arguments: -c "ssh ... labuser@172.30.0.10 ..."     │
│    ├─> RedirectStandardOutput/Error                         │
│    └─> Captura resultado                                    │
│    ↓                                                          │
│ 4. SSH establece conexión con lab_compromised               │
│    - Autenticación con /root/.ssh/id_rsa                    │
│    - Ejecuta comando en máquina remota                      │
│    ↓                                                          │
│ 5. Captura output del comando remoto                        │
│    ↓                                                          │
│ 6. Report() - Registra resultado en logs                    │
│    ↓                                                          │
│ 7. Thread.Sleep(DelayAfter) - Espera post-ejecución        │
│    ↓                                                          │
│ 8. Loop: Vuelve al paso 1 con siguiente comando            │
└──────────────────────────────────────────────────────────────┘
```

### Fase 4: Logging y Monitoreo

**Formato de logs TIMELINE:**
```json
{
  "Handler": "Command",
  "Command": "ssh -o StrictHostKeyChecking=no ... labuser@172.30.0.10 \"...'\"",
  "Result": "[GHOSTS-TEST] SSH connection successful at Wed Nov 26 21:41:35 UTC 2025\n"
}
```

**Ejemplo de ejecución real:**

```
21:41:35 | TRACE | Command line: ssh ... "echo '[GHOSTS-TEST] ...'"
21:41:35 | TRACE | Spawning bash with command ssh ...
21:41:35 | INFO  | TIMELINE | Result: "[GHOSTS-TEST] SSH connection successful at Wed Nov 26 21:41:35 UTC 2025"

21:42:10 | TRACE | Command line: ssh ... "whoami && hostname"
21:42:10 | TRACE | Spawning bash with command ssh ...
21:42:10 | INFO  | TIMELINE | Result: "labuser\n62c13c906f6f\n"

21:42:45 | TRACE | Command line: ssh ... "ping -c 2 172.31.0.10"
21:42:45 | TRACE | Spawning bash with command ssh ...
21:42:46 | INFO  | TIMELINE | Result: "PING 172.31.0.10 ... 2 packets transmitted, 2 received, 0% packet loss"
```

---

## Configuración Técnica

### application.json

Configuración del cliente GHOSTS:

```json
{
  "Sockets": {
    "IsEnabled": false          // Modo offline, sin servidor GHOSTS API
  },
  "Id": {
    "IsEnabled": false          // Sin registro de ID en servidor
  },
  "EncodeHeaders": false,
  "ClientResults": {
    "IsEnabled": false          // No envía resultados a servidor
  },
  "ClientUpdates": {
    "IsEnabled": false          // No recibe actualizaciones de servidor
  },
  "Survey": {
    "IsEnabled": false          // No realiza encuestas del sistema
  },
  "Logging": {
    "Level": "Trace",           // Máximo nivel de detalle
    "OutputMode": "file"        // Guarda logs en archivos
  }
}
```

### timeline.json

Define el comportamiento automatizado:

| Parámetro | Descripción |
|-----------|-------------|
| `Status` | `"Run"` - Timeline activo |
| `HandlerType` | `"Bash"` - Usa el handler de comandos bash |
| `Loop` | `true` - Ejecuta comandos en bucle infinito |
| `UtcTimeOn/Off` | Horario de operación (00:00 - 23:59) |
| `DelayBefore` | Milisegundos de espera antes del comando |
| `DelayAfter` | Milisegundos de espera después del comando |

### Handlers de GHOSTS

GHOSTS soporta múltiples handlers, pero en este proyecto solo se usa:

```csharp
public enum HandlerType {
    BrowserFirefox = 1,
    BrowserChrome = 2,
    Command = 3,           // Handler genérico de comandos
    // ... otros handlers ...
    Bash = 40,             // ✓ Handler usado en este proyecto
    Ssh = 100,
    // ... más handlers ...
}
```

El **Bash handler** (`Handlers/Bash.cs`):
- Ejecuta comandos shell usando `Process.Start("bash", "-c \"command\"")`
- Captura stdout y stderr
- Reporta resultados al timeline logger
- Soporta jitter y probabilidad de ejecución

---

## Resolución de Problemas

### Problemas Encontrados y Solucionados

#### 1. Handler "Word" en lugar de "Bash"

**Problema:**
```
2025-11-26 21:14:37|TRACE|Attempting new thread for: Word
2025-11-26 21:14:37|INFO|Word handler automation is not currently supported on this OS
```

**Causa:** 
- El Dockerfile copiaba archivos a `/opt/ghosts/config/`
- GHOSTS buscaba en `/opt/ghosts/bin/config/`
- Usaba el timeline por defecto que incluye handler "Word"

**Solución:**
```dockerfile
# ANTES (incorrecto):
COPY images/ghosts_driver/timeline_minimal.json /opt/ghosts/config/timeline.json

# DESPUÉS (correcto):
COPY images/ghosts_driver/timeline_minimal.json /opt/ghosts/bin/config/timeline.json
```

#### 2. Error de formato en application.json

**Problema:**
```
Error converting value "ghosts-driver-001" to type 'ClientConfiguration+IdSettings'
```

**Causa:** 
- Campo `Id` definido como string simple
- GHOSTS espera un objeto con configuración completa

**Solución:**
```json
// ANTES (incorrecto):
{
  "Id": "ghosts-driver-001",
  ...
}

// DESPUÉS (correcto):
{
  "Id": {
    "IsEnabled": false,
    "Format": "guestinfo",
    "FormatKey": "guestinfo.rangename",
    "FormatValue": "$formatkeyvalue$-$machinename$",
    "VMWareToolsLocation": "..."
  },
  ...
}
```

#### 3. NullReferenceException en Program.cs

**Causa:** 
- Archivo application.json incompleto
- Faltaban campos requeridos por GHOSTS

**Solución:**
- Copiar estructura completa del `application.json` de ejemplo
- Configurar todos los campos necesarios con valores apropiados

### Verificación del Sistema

Para confirmar que GHOSTS está funcionando correctamente:

```bash
# 1. Verificar que el contenedor está corriendo
docker ps --filter name=lab_ghosts_driver

# 2. Ver logs de inicialización
docker logs lab_ghosts_driver 2>&1 | head -50

# 3. Buscar inicialización del handler Bash
docker logs lab_ghosts_driver 2>&1 | grep "Attempting new thread"

# 4. Verificar ejecución de comandos SSH
docker logs lab_ghosts_driver 2>&1 | grep "GHOSTS-TEST\|whoami\|ping"

# 5. Ver timeline de resultados
docker logs lab_ghosts_driver 2>&1 | grep "TIMELINE"
```

**Salida esperada:**
```
✓ SSH connection test passed
Attempting new thread for: Bash
Command line: ssh ... labuser@172.30.0.10 ...
Result: "[GHOSTS-TEST] SSH connection successful at ..."
Result: "labuser\n62c13c906f6f\n"
Result: "PING 172.31.0.10 ... 2 received, 0% packet loss"
```

---

## Referencias

- **GHOSTS Framework**: https://github.com/cmu-sei/GHOSTS
- **Documentación oficial**: https://cmu-sei.github.io/GHOSTS/
- **Timeline specification**: `GHOSTS/docs/specification.md`
- **Handlers disponibles**: `GHOSTS/src/Ghosts.Client.Universal/Handlers/`

---

## Resumen

GHOSTS se integra en el proyecto Trident como un **simulador de amenazas automatizado** que:

1. ✅ Se ejecuta en un contenedor Docker independiente (`lab_ghosts_driver`)
2. ✅ Utiliza el handler **Bash** para ejecutar comandos SSH
3. ✅ Se conecta a `lab_compromised` usando autenticación por clave pública
4. ✅ Ejecuta comandos de forma cíclica según el timeline configurado
5. ✅ Genera tráfico de red realista para entrenamiento de sistemas de detección
6. ✅ Registra todas las acciones en logs detallados para análisis posterior

El flujo general es: **GHOSTS Driver → SSH → lab_compromised → Ejecuta comando → Respuesta → GHOSTS registra → Loop**
