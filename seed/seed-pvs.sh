#!/bin/sh
# Seed the configuration_service registry with mini_beamline PVs so the
# direct_control_service's registry-validation gate lets reads/writes through.
#
# Runs once at compose startup as a sidecar; exits after seeding.
set -eu

CONFIG_URL="${CONFIG_URL:-http://configuration_service:8004}"

echo "seed: waiting for $CONFIG_URL to become reachable..."
until curl -sf "$CONFIG_URL/health" > /dev/null; do
    sleep 1
done
echo "seed: config-service reachable, registering PVs..."

# Known PVs from caproto.ioc_examples.mini_beamline (prefix `mini:`).
# Motors are settable floats — the `(motor)` label is a demo convention,
# not a true EPICS motor record.
PVS="
mini:current
mini:dot:img_sum
mini:dot:det
mini:dot:exp
mini:dot:mtrx
mini:dot:mtry
mini:dot:shutter_open
mini:ph1:det
mini:ph1:mtr
mini:ph1:exp
mini:ph1:vel
mini:ph1:mtr_tick_rate
"

for pv in $PVS; do
    # 201 Created on first call, 409 Conflict if already registered — both fine.
    status=$(curl -s -o /tmp/resp -w "%{http_code}" \
        -X POST "$CONFIG_URL/api/v1/pvs" \
        -H "Content-Type: application/json" \
        -d "{\"pv_name\":\"$pv\"}")
    case "$status" in
        2*) echo "  seeded: $pv ($status)" ;;
        409) echo "  already: $pv" ;;
        # Exit non-zero so direct_control_service (depends_on
        # service_completed_successfully) doesn't start against a
        # half-seeded registry and silently 404 every request.
        *)   echo "  FAIL: $pv -> $status: $(cat /tmp/resp)"; exit 1 ;;
    esac
done

echo "seed: done"
