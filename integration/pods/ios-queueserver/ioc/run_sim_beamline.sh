#!/bin/bash
# Orchestrate the simulated IOS beamline inside one container: start the seven
# realistic caproto IOCs (one CA port each, pgm FIRST — the xspress3 sim
# follows the PGM's live energy at 127.0.0.1:5064), harvest the exact PV names
# they serve, then start the blackhole catch-all told to defer on those names.
# Mirrors reproduce.sh's start_iocs, adapted for a container (0.0.0.0 binds;
# confinement is the compose network, not loopback).
#
# Fail-hard: if any IOC fails to start — or ANY IOC process later dies — the
# container exits nonzero so compose surfaces it, rather than serving a
# half-beamline. /tmp/sim-ready is the healthcheck marker.
set -euo pipefail

IOCS="ioc_ios_pgm ioc_ios_curramp ioc_ios_epu ioc_ios_vortex ioc_ios_scaler ioc_ios_feedback ioc_ios_xspress3"
BASE_PORT="${IOC_BASE_PORT:-5064}"
LOG_DIR=/tmp/ioc-logs
EXCLUDE_FILE=/tmp/exclude_pvs.txt
SIM_DATA_ROOT="${SIM_DATA_ROOT:-/sim-data}"

mkdir -p "$LOG_DIR" "$SIM_DATA_ROOT/xs3"

i=0
for name in $IOCS; do
    port=$((BASE_PORT + 2 * i)); i=$((i + 1))
    EPICS_CA_SERVER_PORT="$port" \
    XS3_PGM_ADDR="127.0.0.1:${BASE_PORT}" \
    XS3_HDF_FILE_PATH="$SIM_DATA_ROOT/xs3" \
        python "/app/iocs/${name}.py" --list-pvs --interfaces 0.0.0.0 \
        > "$LOG_DIR/${name}.log" 2>&1 &
done

sleep 6
: > "$EXCLUDE_FILE"
i=0
for name in $IOCS; do
    port=$((BASE_PORT + 2 * i)); i=$((i + 1))
    if ! grep -q "Listening on" "$LOG_DIR/${name}.log"; then
        echo "FATAL: $name did not start (CA port $port):" >&2
        cat "$LOG_DIR/${name}.log" >&2
        exit 1
    fi
    echo "$name -> CA port $port"
    grep -oE 'XF:[^ ]+' "$LOG_DIR/${name}.log" >> "$EXCLUDE_FILE" || true
done
sort -u -o "$EXCLUDE_FILE" "$EXCLUDE_FILE"

BH_PORT=$((BASE_PORT + 2 * i))
BLACKHOLE_EXCLUDE_PVS_FILE="$EXCLUDE_FILE" \
EPICS_CA_SERVER_PORT="$BH_PORT" \
    python /app/iocs/blackhole_ioc.py --interfaces 0.0.0.0 \
    > "$LOG_DIR/blackhole.log" 2>&1 &

sleep 4
if ! grep -q "Listening on" "$LOG_DIR/blackhole.log"; then
    echo "FATAL: blackhole did not start (CA port $BH_PORT):" >&2
    cat "$LOG_DIR/blackhole.log" >&2
    exit 1
fi

touch /tmp/sim-ready
echo "sim beamline ready: 7 realistic IOCs (${BASE_PORT}..$((BH_PORT - 2))) + blackhole (${BH_PORT}), $(wc -l < "$EXCLUDE_FILE") harvested PVs excluded"

# If any IOC process exits, take the container down with it.
wait -n
echo "FATAL: an IOC process exited — bringing the sim beamline down" >&2
exit 1
