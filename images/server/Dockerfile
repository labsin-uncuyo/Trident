FROM ubuntu:22.04

# === BASE PACKAGES (from shared/base-packages.dockerfile) ===
# Avoid interactive prompts and set a default timezone
ENV DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC

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
       iputils-ping gettext-base git unzip openssh-server iptables ufw \
       net-tools procps kmod systemd systemd-sysv \
    && rm -rf /var/lib/apt/lists/*

# === SERVER-SPECIFIC PACKAGES ===
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       nginx rsyslog netcat \
       python3 python3-pip \
       build-essential wget ca-certificates \
       libreadline-dev zlib1g-dev libssl-dev libxml2-dev libxslt1-dev libicu-dev \
       bison flex libuuid1 uuid-dev \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/log/nginx \
    && mkdir -p /var/run/sshd \
    && echo 'root:admin123' | chpasswd \
    && echo "PermitRootLogin yes" >> /etc/ssh/sshd_config

# Build PostgreSQL 11.4 from source for CVE-2019-10208 testing.
ARG PG_SRC_VERSION=11.4
RUN set -e; \
    wget -q -O /tmp/postgresql.tar.gz "https://ftp.postgresql.org/pub/source/v${PG_SRC_VERSION}/postgresql-${PG_SRC_VERSION}.tar.gz"; \
    mkdir -p /usr/src/postgresql; \
    tar -xzf /tmp/postgresql.tar.gz -C /usr/src/postgresql --strip-components=1; \
    cd /usr/src/postgresql; \
    ./configure --prefix=/usr/local/pgsql-${PG_SRC_VERSION}; \
    make -j"$(nproc)"; \
    make install; \
    ln -s /usr/local/pgsql-${PG_SRC_VERSION} /usr/local/pgsql; \
    rm -rf /usr/src/postgresql /tmp/postgresql.tar.gz

# Create postgres system user and data directory
RUN useradd -m -s /bin/bash postgres \
    && mkdir -p /var/lib/postgresql/data /var/log/postgresql \
    && chown -R postgres:postgres /var/lib/postgresql /var/log/postgresql

ENV PATH="/usr/local/pgsql/bin:${PATH}"

COPY app/index.html /var/www/html/index.html
COPY nginx-login.conf /etc/nginx/sites-available/default

RUN mkdir -p /opt/flask_app
COPY flask_app/ /opt/flask_app/
RUN pip3 install --no-cache-dir -r /opt/flask_app/requirements.txt

# Copy SQL database file for manual execution
RUN mkdir -p /opt/database
COPY employees_data_large.sql /opt/database/employees_data_modified.sql
COPY roles_users.sql /opt/database/roles_users.sql
COPY unsafe_definer.sql /opt/database/unsafe_definer.sql

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN printf '/var/log/nginx/*.log {\n    daily\n    missingok\n    rotate 7\n    compress\n    delaycompress\n    notifempty\n    create 0640 www-data adm\n    sharedscripts\n    postrotate\n        [ ! -f /var/run/nginx.pid ] || kill -USR1 `cat /var/run/nginx.pid`\n    endscript\n}\n' > /etc/logrotate.d/nginx-lab

# === OPENCODE INSTALLATION (from shared/opencode-install.dockerfile) ===
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

# Setup systemd service
COPY lab-entrypoint.service /etc/systemd/system/lab-entrypoint.service
RUN systemctl enable lab-entrypoint

EXPOSE 80 5432 22

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD bash -lc "curl -fsS http://127.0.0.1:80 >/dev/null && pg_isready -U postgres"

CMD ["/sbin/init"]
