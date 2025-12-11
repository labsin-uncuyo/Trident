# Use official SLIPS and fix the resource module issue
FROM stratosphereips/slips:latest

# Fix the Python resource module issue
RUN apt-get update && \
    apt-get install -y --fix-missing python3.10-resource || \
    apt-get install -y python3.10-minimal && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* || true

# Create directories needed for defender
RUN mkdir -p /opt/lab/defender /root/.ssh && \
    chmod 700 /root/.ssh

# Copy custom defender scripts and SSH setup
COPY ./defender /opt/lab/defender/
COPY ./setup_ssh_keys.sh /opt/lab/setup_ssh_keys.sh
COPY ./slips_entrypoint.sh /opt/lab/slips_entrypoint.sh
COPY ./sync_alerts.py /opt/lab/sync_alerts.py
COPY ./watch_pcaps.py /opt/lab/watch_pcaps.py
COPY ./forward_alerts.py /opt/lab/forward_alerts.py
COPY ./defender_api.py /opt/lab/defender_api.py

# Set proper permissions
RUN chmod +x /opt/lab/defender/*.py /opt/lab/setup_ssh_keys.sh /opt/lab/slips_entrypoint.sh /opt/lab/sync_alerts.py /opt/lab/watch_pcaps.py /opt/lab/forward_alerts.py /opt/lab/defender_api.py