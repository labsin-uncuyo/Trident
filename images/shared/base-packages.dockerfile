# Avoid interactive prompts and set a default timezone
ENV DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC

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