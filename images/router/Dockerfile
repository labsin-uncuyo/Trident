FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates iproute2 iptables logrotate netcat-openbsd procps tcpdump iputils-ping \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
COPY management.sh /management.sh
RUN chmod +x /entrypoint.sh /management.sh

RUN printf '/pcaps/*.pcap {\n    size 10M\n    rotate 5\n    missingok\n    notifempty\n    copytruncate\n    su root root\n}\n' > /etc/logrotate.d/pcap

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD sh -c "sysctl net.ipv4.ip_forward | grep -q 1"

CMD ["/entrypoint.sh"]
