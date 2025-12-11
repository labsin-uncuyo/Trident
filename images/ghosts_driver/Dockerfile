FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Dependencias base: Git, SSH, herramientas de red
RUN apt-get update && apt-get install -y \
    wget curl git openssh-client iputils-ping \
    ca-certificates gnupg2 software-properties-common \
    libicu-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Instalar .NET SDK 9.0
RUN wget https://dot.net/v1/dotnet-install.sh -O dotnet-install.sh \
    && chmod +x dotnet-install.sh \
    && ./dotnet-install.sh --channel 9.0 --install-dir /usr/share/dotnet \
    && rm dotnet-install.sh \
    && ln -s /usr/share/dotnet/dotnet /usr/bin/dotnet

# Verificar instalación de .NET
RUN dotnet --version

# Crear directorios
RUN mkdir -p /opt/ghosts/config /root/.ssh

# Copiar el repositorio GHOSTS desde el host
COPY external/GHOSTS /opt/ghosts_repo

# Compilar el cliente GHOSTS Universal para Linux ARM64
WORKDIR /opt/ghosts_repo/src/Ghosts.Client.Universal
RUN dotnet publish -c Release -r linux-arm64 --self-contained true -o /opt/ghosts/bin

# Crear enlace simbólico al ejecutable
WORKDIR /opt/ghosts
RUN ln -s /opt/ghosts/bin/Ghosts.Client.Universal /opt/ghosts/ghosts.client.linux \
    && chmod +x /opt/ghosts/ghosts.client.linux

# Configuración SSH (Llave Privada)
COPY images/ghosts_driver/john_scott_dummy/id_rsa /root/.ssh/id_rsa
RUN chmod 600 /root/.ssh/id_rsa \
    && chmod 700 /root/.ssh

# Configuración del Timeline de John Scott (debe ir en bin/config donde GHOSTS lo busca)
COPY images/ghosts_driver/john_scott_dummy/timeline_john_scott.json /opt/ghosts/bin/config/timeline.json
COPY images/ghosts_driver/application.json /opt/ghosts/bin/config/application.json

# Script de inicio
COPY images/ghosts_driver/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /opt/ghosts

CMD ["/entrypoint.sh"]
