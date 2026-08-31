#!/usr/bin/env bash
# Start the whole simulated IOS beamline in one process namespace.
#
# Mirrors reproduce.sh's start_iocs(): each realistic IOC gets its own CA
# server port (IOC_BASE_PORT + 2n) and is started with --list-pvs so the exact
# PV names it serves can be harvested; the blackhole catch-all then starts on
# the next slot with that list as its exclusion set, so it never answers a PV
# a realistic IOC owns. Servers bind IOC_INTERFACES (0.0.0.0 by default, so a
# sibling container can reach them); the only CA *client* in here — the
# Xspress3 sim's PGM energy follower — is pointed at 127.0.0.1, which is what
# localguard requires.
#
# Fails hard: if any IOC does not come up, or exits later, this script exits
# non-zero so the container (and its healthcheck) reports it instead of
# serving a half-beamline.
#
# Environment:
#   IOC_DIR            directory holding the IOC scripts        (default /app)
#   IOC_BASE_PORT      first IOC's CA port                        (default 5064)
#   IOC_INTERFACES     server bind address                        (default 0.0.0.0)
#   IOS_IOCS_RUN_DIR   logs, exclusion list, readiness file       (default /tmp/ios_iocs)
#   XS3_HDF_FILE_PATH  Xspress3 sim HDF path (no file IO happens) (default /tmp/xs3)
set -euo pipefail

IOC_DIR="${IOC_DIR:-/app}"
IOC_BASE_PORT="${IOC_BASE_PORT:-5064}"
IOC_INTERFACES="${IOC_INTERFACES:-0.0.0.0}"
RUN_DIR="${IOS_IOCS_RUN_DIR:-/tmp/ios_iocs}"
export XS3_HDF_FILE_PATH="${XS3_HDF_FILE_PATH:-/tmp/xs3}"

# Keep in step with IOS_IOCS in reproduce.sh: ioc_ios_pgm must stay first
# (the Xspress3 follower is pointed at slot 0).
IOS_IOCS="ioc_ios_pgm ioc_ios_curramp ioc_ios_epu ioc_ios_vortex ioc_ios_scaler ioc_ios_feedback ioc_ios_xspress3 ioc_ios_motor"

mkdir -p "$RUN_DIR"
rm -f "$RUN_DIR/ready"
exclude_file="$RUN_DIR/exclude_pvs.txt"
: > "$exclude_file"

wait_listening() {  # $1 = log file, $2 = label
    local n=0
    until grep -q "Listening on" "$1" 2>/dev/null; do
        n=$((n + 1))
        if [ "$n" -ge 120 ]; then
            echo "run_all_iocs: $2 did not start within 60s; log follows" >&2
            cat "$1" >&2
            return 1
        fi
        sleep 0.5
    done
}

i=0
for name in $IOS_IOCS; do
    port=$((IOC_BASE_PORT + 2 * i))
    i=$((i + 1))
    [ -f "$IOC_DIR/$name.py" ] || { echo "run_all_iocs: missing $IOC_DIR/$name.py" >&2; exit 1; }
    EPICS_CA_SERVER_PORT="$port" XS3_PGM_ADDR="127.0.0.1:$IOC_BASE_PORT" \
        python "$IOC_DIR/$name.py" --list-pvs --interfaces "$IOC_INTERFACES" \
        > "$RUN_DIR/$name.log" 2>&1 &
done

i=0
for name in $IOS_IOCS; do
    port=$((IOC_BASE_PORT + 2 * i))
    i=$((i + 1))
    wait_listening "$RUN_DIR/$name.log" "$name"
    # Harvest the exact PV names this IOC serves (from its --list-pvs dump).
    grep -oE 'XF:[^ ]+' "$RUN_DIR/$name.log" >> "$exclude_file" || true
    echo "run_all_iocs: $name -> CA port $port"
done
sort -u -o "$exclude_file" "$exclude_file"
echo "run_all_iocs: harvested $(wc -l < "$exclude_file" | tr -d ' ') realistic PVs (blackhole will defer)"

blackhole_port=$((IOC_BASE_PORT + 2 * i))
EPICS_CA_SERVER_PORT="$blackhole_port" BLACKHOLE_EXCLUDE_PVS_FILE="$exclude_file" \
    python "$IOC_DIR/blackhole_ioc.py" --interfaces "$IOC_INTERFACES" \
    > "$RUN_DIR/blackhole.log" 2>&1 &
wait_listening "$RUN_DIR/blackhole.log" "blackhole"
echo "run_all_iocs: blackhole (catch-all) -> CA port $blackhole_port"

touch "$RUN_DIR/ready"
echo "run_all_iocs: simulated IOS beamline up (ports $IOC_BASE_PORT..$blackhole_port step 2)"

# Any child exiting is a failure of the whole beamline.
wait -n || true
echo "run_all_iocs: an IOC process exited; stopping the rest" >&2
rm -f "$RUN_DIR/ready"
kill $(jobs -p) 2>/dev/null || true
exit 1
