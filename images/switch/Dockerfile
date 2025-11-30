FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates iproute2 logrotate netcat-openbsd tcpdump iputils-ping \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD bash -lc "ss -ltn | grep -q ':7000'"

CMD ["/entrypoint.sh"]
