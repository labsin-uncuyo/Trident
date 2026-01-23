FROM ubuntu:22.04

# === BASE PACKAGES (from shared/base-packages.dockerfile) ===
# Avoid interactive prompts and set a default timezone
ENV DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC

# --------------------------------------------------------------------
# Install base packages with timezone configuration and common tools
RUN apt-get update \
    # Install tzdata first and configure it non-interactively
    && apt-get install -y --no-install-recommends tzdata \
    && ln -fs /usr/share/zoneinfo/$TZ /etc/localtime \
    && dpkg-reconfigure --frontend noninteractive tzdata \
    # Now install the rest of the toolset
    && apt-get install -y --no-install-recommends \
       ubuntu-standard \
       sudo \
       less vim nano htop \
       man-db manpages \
       tcpdump traceroute dnsutils \
       ca-certificates curl iproute2 logrotate \
       iputils-ping gettext-base ripgrep fzf git unzip openssh-server iptables ufw \
       net-tools procps kmod systemd systemd-sysv \
    && rm -rf /var/lib/apt/lists/*

# --------------------------------------------------------------------
# COMPROMISED-SPECIFIC PACKAGES
# --------------------------------------------------------------------
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       # Additional networking tools
       nmap netcat-openbsd socat hydra sshpass \
       # Python
       python3 python3-pip \
       # PostgreSQL client for remote database access
       postgresql-client \
       # Additional utilities
       wget zip tar \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -s /bin/bash labuser \
    && mkdir -p /var/run/sshd \
    && ssh-keygen -A

# Allow labuser passwordless sudo (used by ARACNE when elevated actions are required)
RUN echo "labuser ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/labuser \
    && chmod 440 /etc/sudoers.d/labuser

# Provide a small built-in wordlist for brute-force experiments (used by ARACNE)
COPY wordlists/rockyou.txt /usr/share/wordlists/rockyou.txt

# --------------------------------------------------------------------
# OPENCODE INSTALLATION (from shared/opencode-install.dockerfile)
# --------------------------------------------------------------------
RUN curl -fsSL https://opencode.ai/install | bash

# Add OpenCode to PATH
ENV PATH="/root/.opencode/bin:${PATH}"

# Create config directories
RUN mkdir -p /root/.config/opencode \
    && mkdir -p /root/.local/share/opencode

# Copy OpenCode configuration template
COPY opencode.json /root/.config/opencode/opencode.json.template

# Create symlink for opencode in system PATH
RUN ln -sf /root/.opencode/bin/opencode /usr/local/bin/opencode

# --------------------------------------------------------------------
# Entrypoint setup
# --------------------------------------------------------------------
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22

# --------------------------------------------------------------------
# Healthcheck: SSH service responding
# --------------------------------------------------------------------
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD bash -lc "ss -ltn | grep -q ':22'"

CMD ["/entrypoint.sh"]
