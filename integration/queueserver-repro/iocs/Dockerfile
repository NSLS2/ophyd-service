# Simulated IOS beamline image: the eight realistic caproto IOCs plus the
# blackhole catch-all, run together by run_all_iocs.sh in ONE container so the
# Xspress3 sim's PGM follower (a CA client that localguard restricts to loopback)
# can reach the PGM IOC on 127.0.0.1 — the same topology reproduce.sh uses on a
# host. This directory is the single source of the IOC scripts; the compose
# pods under integration/pods/ios build from it.
#
# No apt, no pgrep: readiness is a file the launcher touches, so the image
# builds on networks that only allow pip.
FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir caproto numpy

COPY *.py run_all_iocs.sh /app/
RUN chmod +x /app/run_all_iocs.sh \
    && useradd -m -u 1000 ioc && chown -R ioc:ioc /app
USER ioc

# One CA port per IOC from IOC_BASE_PORT (default 5064) stepping by 2, blackhole
# on the slot after the last IOC (5080 with the eight shipped here).
CMD ["/app/run_all_iocs.sh"]
