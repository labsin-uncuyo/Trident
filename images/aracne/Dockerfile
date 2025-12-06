FROM python:3.12-slim

WORKDIR /agent

COPY external/aracne/requirements.txt .

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client sshpass \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt

COPY external/aracne/agent/ /agent

# Remove upstream start_lab.sh directory (we mount our own launcher)
RUN rm -rf /agent/start_lab.sh

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

CMD ["bash"]
