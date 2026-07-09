# Catch-all EPICS IOC image for the IOS demo pod.
FROM python:3.11-slim

WORKDIR /app

# procps provides pgrep for the compose healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends procps \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir caproto numpy

COPY blackhole_ioc.py /app/blackhole_ioc.py

# Channel Access: 5064/tcp+udp (search + virtual circuits), 5065/udp (repeater).
EXPOSE 5064/tcp 5064/udp 5065/udp

CMD ["python", "/app/blackhole_ioc.py", "--list-pvs", "--interfaces", "0.0.0.0"]
