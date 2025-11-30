
# Propuesta de Integración GHOSTS: Arquitectura "Titiritero" (Puppeteer)

## 1\. Concepto General

El objetivo es integrar el framework **GHOSTS** para simular la actividad de usuarios (NPCs) sin "contaminar" la máquina víctima (`lab_compromised`) con binarios o agentes de simulación.

Para lograr esto, se implementa una arquitectura de **"Titiritero" (Puppeteer)**:

  * **Nivel Superior (Driver):** Un contenedor dedicado que aloja el cliente GHOSTS. Este contenedor actúa como el operador humano.
  * **Nivel Inferior (Víctima):** La máquina `lab_compromised` existente. Esta máquina es "conducida" remotamente.

El agente GHOSTS se ejecuta en el contenedor *Driver* y envía comandos vía **SSH** hacia la máquina *Víctima*. De esta forma, el tráfico de red generado (HTTP, DNS, etc.) **se origina legítimamente desde la IP de la víctima** (172.30.0.10), siendo detectado correctamente por el IDS (SLIPS), manteniendo la máquina víctima limpia de software de prueba.

## 2\. Estructura de Directorios

Se añade un nuevo directorio al nivel de las imágenes para alojar la lógica del conductor.

```text
/
├── docker-compose.yml
├── images/
│   ├── compromised/       # Imagen existente de la víctima
│   │   ├── Dockerfile     # (Modificado para aceptar SSH Key)
│   │   └── ...
│   ├── ghosts_driver/     # NUEVO: Contenedor "Titiritero"
│   │   ├── Dockerfile     # Cliente GHOSTS + Cliente SSH
│   │   ├── id_rsa         # Llave privada (generada localmente)
│   │   ├── id_rsa.pub     # Llave pública (se copia a la víctima)
│   │   └── timeline.json  # Guión de comportamiento (SSH wrappers)
│   └── ...
```

## 3\. Implementación Técnica

### A. Gestión de Identidad (SSH Keys)

Para permitir que GHOSTS controle la máquina sin intervención manual, se utiliza autenticación por par de llaves RSA sin contraseña.

1.  **Generación de llaves (en host local):**
    ```bash
    ssh-keygen -t rsa -b 4096 -f ./images/ghosts_driver/id_rsa -q -N ""
    ```
2.  **Distribución:**
      * `id_rsa` (Privada) -\> Se copia al contenedor `ghosts_driver`.
      * `id_rsa.pub` (Pública) -\> Se inyecta en `lab_compromised` (`authorized_keys`).

### B. Configuración del Driver (`images/ghosts_driver/`)

**Dockerfile:**
Este contenedor prepara el entorno para ejecutar GHOSTS y conectarse a la víctima.

```dockerfile
FROM ubuntu:22.04

# Dependencias: GHOSTS (.NET deps) + Cliente SSH
RUN apt-get update && apt-get install -y \
    wget unzip openssh-client libicu-dev iputils-ping \
    && rm -rf /var/lib/apt/lists/*

# Instalación del Cliente GHOSTS
WORKDIR /opt/ghosts
RUN wget https://github.com/cmu-sei/GHOSTS/releases/download/v8.0.0/ghosts-client-linux-x64.zip \
    && unzip ghosts-client-linux-x64.zip \
    && chmod +x ghosts.client.linux

# Configuración SSH (Llave Privada)
COPY id_rsa /root/.ssh/id_rsa
RUN chmod 600 /root/.ssh/id_rsa

# Configuración del Timeline
COPY timeline.json /opt/ghosts/config/timeline.json

# Ejecución
CMD ["./ghosts.client.linux"]
```

**Timeline (`timeline.json`):**
En lugar de ejecutar acciones locales, el timeline envuelve los comandos en sesiones SSH dirigidas a la víctima.

```json
{
  "Status": "Run",
  "TimeLineHandlers": [
    {
      "HandlerType": "Command",
      "Initial": "",
      "UtcTimeOn": "00:00:00",
      "UtcTimeOff": "23:59:00",
      "Loop": true,
      "TimeLineEvents": [
        {
          "Command": "ssh",
          "CommandArgs": [
            "-o", "StrictHostKeyChecking=no",
            "-i", "/root/.ssh/id_rsa",
            "labuser@172.30.0.10", 
            "curl -s http://172.31.0.10:8080/index.html"
          ],
          "DelayAfter": 5000
        },
        {
          "Command": "ssh",
          "CommandArgs": [
            "-o", "StrictHostKeyChecking=no",
            "-i", "/root/.ssh/id_rsa",
            "labuser@172.30.0.10", 
            "wget -O /dev/null http://172.31.0.10:8080/suspicious_file"
          ],
          "DelayAfter": 15000
        }
      ]
    }
  ]
}
```

### C. Integración en `docker-compose.yml`

Se añade el servicio driver en la misma red que la víctima para tener visibilidad directa.

```yaml
services:
  # ... servicios existentes ...

  lab_ghosts_driver:
    build: 
      context: .
      dockerfile: images/ghosts_driver/Dockerfile
    container_name: lab_ghosts_driver
    networks:
      lab_net_a: # Red compartida con lab_compromised
    depends_on:
      - lab_compromised
```

## 4\. Flujo de Ejecución y Detección

1.  **Inicio:** Al ejecutar `make up`, se levanta la infraestructura y el nuevo contenedor `lab_ghosts_driver`.
2.  **Comando:** GHOSTS lee el `timeline.json` y ejecuta el comando `ssh labuser@172.30.0.10 "curl ..."`.
3.  **Ejecución Remota:** La máquina `lab_compromised` recibe la instrucción SSH y ejecuta el `curl` localmente.
4.  **Generación de Tráfico:** El paquete HTTP sale de `172.30.0.10` con destino al servidor `172.31.0.10`.
5.  **Intercepción:**
      * El paquete pasa por `lab_router`.
      * Se hace un mirror hacia `lab_switch`.
      * Se guarda en `outputs/${RUN_ID}/pcaps/`.
6.  **Análisis:** SLIPS ingesta el PCAP y detecta la actividad, atribuyéndola correctamente a la IP de la máquina comprometida, cumpliendo el objetivo del laboratorio de investigación.

https://github.com/cmu-sei/GHOSTS