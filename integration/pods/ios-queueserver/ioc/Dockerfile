# Simulated IOS beamline image: the SHARED sim suite from
# integration/queueserver-repro/iocs (7 realistic caproto IOCs + the blackhole
# catch-all with type rules), orchestrated by run_sim_beamline.sh — one
# container, one CA server per port (5064 + 2n, blackhole on 5078).
#
# Build context is integration/ (see docker-compose.yaml) so this image copies
# the canonical IOC sources instead of keeping a stale duplicate here.
#
# Full (non-slim) python base on purpose: it ships procps (pgrep for
# healthchecks) so no apt layer is needed — pip is the only network step.
FROM docker.io/python:3.11

RUN pip install --no-cache-dir caproto numpy

WORKDIR /app
COPY queueserver-repro/iocs/ /app/iocs/
COPY pods/ios-queueserver/ioc/run_sim_beamline.sh /app/run_sim_beamline.sh
RUN chmod +x /app/run_sim_beamline.sh

# Channel Access: one server port per IOC (search + circuits on the same
# number), 5064..5076 realistic + 5078 blackhole; 5065/udp is the repeater.
EXPOSE 5064-5078/tcp 5064-5078/udp

CMD ["/app/run_sim_beamline.sh"]
