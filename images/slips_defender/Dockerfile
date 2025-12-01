# Extend the official SLIPS image with SSH client for auto_responder
FROM stratosphereips/slips:latest

# Install SSH client and related tools (already running as root)
# Also install missing Python dependencies like umap
RUN apt-get update && apt-get install -y \
    openssh-client \
    sshpass \
    netcat-openbsd \
    telnet \
    iputils-ping \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install umap and other missing Python dependencies
RUN pip3 install --no-cache-dir umap-learn

# Install defender requirements
COPY ./defender/requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Create directory for SSH keys (volume will be mounted at /root/.ssh)
RUN mkdir -p /root/.ssh && chmod 700 /root/.ssh

# Create SSH keys in persistent location if they don't exist
RUN if [ ! -f /root/.ssh/id_rsa_auto_responder ]; then \
    ssh-keygen -t ed25519 -f /root/.ssh/id_rsa_auto_responder -N "" -C "auto_responder@slips" && \
    chmod 600 /root/.ssh/id_rsa_auto_responder && \
    chmod 644 /root/.ssh/id_rsa_auto_responder.pub; \
    fi

# Copy custom defender scripts and SSH setup
COPY ./defender /opt/lab/defender/
COPY ./setup_ssh_keys.sh /opt/lab/setup_ssh_keys.sh

# Set proper permissions
RUN chmod +x /opt/lab/defender/*.py /opt/lab/setup_ssh_keys.sh
