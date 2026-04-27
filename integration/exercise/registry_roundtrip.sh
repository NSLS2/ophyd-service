#!/usr/bin/env bash
#
# Exercise the registry-lifecycle contract end to end.
#
# Validates the full round-trip:
#   1. configuration_service starts up with a single-IOC happi seed
#      (mini_beamline only — see integration/happi/happi_db.json)
#   2. The CRUD API accepts additional devices for the OTHER IOCs we run
#      (motor records, random walks, thermo) — exactly how a real beamline
#      would extend its registry as new instruments come online.
#   3. /api/v1/registry/export returns the COMBINED state in happi format —
#      every entry has the required happi shape.
#   4. That export is itself a valid happi profile: a fresh
#      configuration_service container loaded against it ends up with the
#      same device count and names. Closes the loop on "the export is
#      reimportable" — without that, export is just a debug dump.
#
# Pre-req: a pod must be up (any of minimal/full/dev), with the trimmed
# canonical happi mounted. The script makes no assumptions about which one.
#
# Pre-req: docker must be reachable as the current user. If not, run via
#   sg docker -c '/path/to/registry_roundtrip.sh'
#
# Usage:
#   ./registry_roundtrip.sh
#   CONFIG_URL=http://remote:8004 SIDE_PORT=8204 ./registry_roundtrip.sh

set -euo pipefail

CONFIG_URL="${CONFIG_URL:-http://localhost:8004}"
SIDE_PORT="${SIDE_PORT:-8104}"
SIDE_HEALTH_TIMEOUT="${SIDE_HEALTH_TIMEOUT:-30}"
SIDE_NAME="roundtrip_check_cs"
WORK_DIR="${WORK_DIR:-/tmp/roundtrip_check}"

if [ -t 1 ]; then
    GREEN=$'\033[32m'; RED=$'\033[31m'; YELLOW=$'\033[33m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
else
    GREEN=''; RED=''; YELLOW=''; BOLD=''; RESET=''
fi

step() { printf "\n${BOLD}== %s ==${RESET}\n" "$1"; }
pass() { printf "  ${GREEN}PASS${RESET}  %s\n" "$1"; }
fail() { printf "  ${RED}FAIL${RESET}  %s\n" "$1" >&2; cleanup; exit 1; }
note() { printf "  ${YELLOW}NOTE${RESET}  %s\n" "$1"; }

req() {
    local method=$1 url=$2 body="${3:-}"
    local -a args=(-s -o /tmp/exer_body -w "%{http_code}" -X "$method")
    if [ -n "$body" ]; then
        args+=(-H "Content-Type: application/json" -d "$body")
    fi
    curl "${args[@]}" "$url"
}

expect_status() {
    local want=$1 got=$2 url=$3
    if [ "$got" != "$want" ]; then
        printf "    response body: %s\n" "$(cat /tmp/exer_body 2>/dev/null | head -c 400)"
        fail "$url: expected HTTP $want, got $got"
    fi
}

# Track devices we add so we can clean them up at the end (or on failure).
ADDED_DEVICES=()

cleanup() {
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$SIDE_NAME"; then
        printf "  (cleanup) killing side container %s\n" "$SIDE_NAME"
        docker kill "$SIDE_NAME" >/dev/null 2>&1 || true
    fi
    if [ ${#ADDED_DEVICES[@]} -gt 0 ]; then
        printf "  (cleanup) deleting %d CRUD-added devices\n" "${#ADDED_DEVICES[@]}"
        for name in "${ADDED_DEVICES[@]}"; do
            curl -s -o /dev/null -X DELETE "${CONFIG_URL}/api/v1/devices/${name}" || true
        done
    fi
    rm -rf "$WORK_DIR"
}

trap cleanup EXIT

# ─── CRUD helpers ───────────────────────────────────────────────────────

# crud_add_signal NAME PREFIX [LABEL]  → register a flat EpicsSignal device.
crud_add_signal() {
    local name=$1 prefix=$2 label="${3:-signal}"
    local body
    body=$(jq -n --arg n "$name" --arg p "$prefix" --arg l "$label" '{
        metadata: {
            name: $n, device_label: $l, ophyd_class: "EpicsSignal",
            is_movable: true, is_readable: true,
            pvs: {readback: $p},
            documentation: "added by registry_roundtrip"
        },
        instantiation_spec: {
            name: $n, device_class: "ophyd.signal.EpicsSignal",
            args: [$p], kwargs: {name: $n}, active: true
        }
    }')
    local status
    status=$(req POST "${CONFIG_URL}/api/v1/devices" "$body")
    case "$status" in
        20*) ADDED_DEVICES+=("$name"); pass "POST $name @ $prefix  HTTP $status" ;;
        *)   expect_status 201 "$status" "POST $name @ $prefix" ;;
    esac
}

# crud_add_motor NAME PREFIX  → register an ophyd.EpicsMotor (real motor record).
crud_add_motor() {
    local name=$1 prefix=$2
    local body
    body=$(jq -n --arg n "$name" --arg p "$prefix" '{
        metadata: {
            name: $n, device_label: "motor", ophyd_class: "EpicsMotor",
            is_movable: true, is_readable: true,
            pvs: {
                user_setpoint: $p,
                user_readback: ($p + ".RBV"),
                velocity: ($p + ".VELO"),
                acceleration: ($p + ".ACCL")
            },
            documentation: "added by registry_roundtrip"
        },
        instantiation_spec: {
            name: $n, device_class: "ophyd.EpicsMotor",
            args: [$p], kwargs: {name: $n}, active: true
        }
    }')
    local status
    status=$(req POST "${CONFIG_URL}/api/v1/devices" "$body")
    case "$status" in
        20*) ADDED_DEVICES+=("$name"); pass "POST $name @ $prefix (EpicsMotor)  HTTP $status" ;;
        *)   expect_status 201 "$status" "POST $name @ $prefix" ;;
    esac
}

# crud_add_compound NAME PREFIX DEVICE_CLASS  → register a localdevs.* compound.
crud_add_compound() {
    local name=$1 prefix=$2 device_class=$3
    local class_short="${device_class##*.}"
    local body
    body=$(jq -n --arg n "$name" --arg p "$prefix" --arg dc "$device_class" --arg c "$class_short" '{
        metadata: {
            name: $n, device_label: "detector", ophyd_class: $c,
            is_readable: true, is_triggerable: true,
            pvs: {prefix: $p},
            documentation: "added by registry_roundtrip"
        },
        instantiation_spec: {
            name: $n, device_class: $dc,
            args: [$p], kwargs: {name: $n}, active: true
        }
    }')
    local status
    status=$(req POST "${CONFIG_URL}/api/v1/devices" "$body")
    case "$status" in
        20*) ADDED_DEVICES+=("$name"); pass "POST $name @ $prefix ($class_short)  HTTP $status" ;;
        *)   expect_status 201 "$status" "POST $name @ $prefix" ;;
    esac
}

# ─── Banner ─────────────────────────────────────────────────────────────
printf "${BOLD}registry_roundtrip exerciser${RESET}  target=${CONFIG_URL}  side_port=${SIDE_PORT}\n"

# ─── 1. Snapshot initial state ──────────────────────────────────────────
step "Initial state (happi-seeded)"

status=$(req GET "${CONFIG_URL}/health")
expect_status 200 "$status" "/health"
initial_count=$(jq -r '.devices_loaded' < /tmp/exer_body)
pass "/health  initial devices_loaded=${initial_count}"

status=$(req GET "${CONFIG_URL}/api/v1/devices")
expect_status 200 "$status" "/api/v1/devices"
mapfile -t initial_names < <(jq -r '.[]? // keys[]' < /tmp/exer_body | sort)
pass "captured ${#initial_names[@]} initial device names"

# ─── 2. CRUD-add devices for the other IOCs ─────────────────────────────
step "CRUD-add devices for the other IOCs"

# fake_motor_record IOC — three real motor records
crud_add_motor motor1 sim:mtr1
crud_add_motor motor2 sim:mtr2
crud_add_motor motor3 sim:mtr3

# random_walk IOCs — three RandomWalk compounds + leaf scalars (dt + x)
crud_add_compound random_walk    "random_walk:"        localdevs.RandomWalk
crud_add_compound random_walk_h  "random_walk:horiz-"  localdevs.RandomWalk
crud_add_compound random_walk_v  "random_walk:vert-"   localdevs.RandomWalk
crud_add_signal random_walk_dt    "random_walk:dt"
crud_add_signal random_walk_x     "random_walk:x"
crud_add_signal random_walk_h_dt  "random_walk:horiz-dt"
crud_add_signal random_walk_h_x   "random_walk:horiz-x"
crud_add_signal random_walk_v_dt  "random_walk:vert-dt"
crud_add_signal random_walk_v_x   "random_walk:vert-x"

# thermo_sim IOC — Thermo compound + leaf scalars (I/SP/K/omega/Tvar)
crud_add_compound thermo "thermo:" localdevs.Thermo
crud_add_signal thermo_I     "thermo:I"
crud_add_signal thermo_SP    "thermo:SP"
crud_add_signal thermo_K     "thermo:K"
crud_add_signal thermo_omega "thermo:omega"
crud_add_signal thermo_Tvar  "thermo:Tvar"

# ─── 3. Verify additions landed ─────────────────────────────────────────
step "Verify additions landed in registry"

status=$(req GET "${CONFIG_URL}/health")
post_crud_count=$(jq -r '.devices_loaded' < /tmp/exer_body)
expected_count=$(( initial_count + ${#ADDED_DEVICES[@]} ))
[ "$post_crud_count" = "$expected_count" ] \
    || fail "post-CRUD count $post_crud_count != expected $expected_count (initial $initial_count + ${#ADDED_DEVICES[@]} CRUD)"
pass "/health  devices_loaded=${post_crud_count} (matches initial + CRUD)"

# Spot-check a few of the additions are reachable via GET
for name in motor1 thermo random_walk_x; do
    status=$(req GET "${CONFIG_URL}/api/v1/devices/${name}")
    expect_status 200 "$status" "GET /api/v1/devices/${name}"
done
pass "spot-checked motor1, thermo, random_walk_x — all retrievable"

# ─── 4. direct_control monitors a CRUD-added PV ─────────────────────────
# This is the real-beamline contract: a device added at runtime via CRUD
# should be immediately monitorable through direct_control — registry gate
# accepts it, CA connects, WS subscribe receives updates.
step "direct_control monitors a CRUD-added PV (registry-gate + CA + WS round-trip)"

DIRECT_URL="${DIRECT_URL:-http://localhost:8003}"

# Candidate PVs in priority order — pick the first one with both a CRUD
# entry in the registry (just added above) AND a live IOC.
candidates=(
    "random_walk:x"     # full pod   — caproto.ioc_examples.random_walk
    "thermo:I"          # full pod   — caproto.ioc_examples.thermo_sim
    "sim:mtr1.RBV"      # dev pod    — caproto.ioc_examples.fake_motor_record
)

chosen=""
for pv in "${candidates[@]}"; do
    code=$(curl -s -o /tmp/exer_body -w "%{http_code}" \
        "${DIRECT_URL}/api/v1/pv/${pv}/value")
    if [ "$code" = "200" ]; then
        chosen="$pv"
        value=$(jq -r '.value' < /tmp/exer_body)
        pass "HTTP read of CRUD-added ${pv}: value=${value}"
        break
    fi
done

if [ -z "$chosen" ]; then
    note "no live CRUD-added PV reachable through direct_control."
    note "CRUD-added devices are in the registry, but their IOCs aren't running."
    note "Bring up the 'full' pod (random_walk + thermo) or 'dev' pod (motor records)"
    note "to exercise the registry → CA round-trip end to end."
else
    # WS subscribe round-trip via the companion python exerciser. Hands off
    # to direct_control_ws.py so the WS protocol details stay in one place.
    ws_script="$(dirname "$0")/direct_control_ws.py"
    if [ -x "$ws_script" ] && command -v uv >/dev/null; then
        if PV_NAME="$chosen" UPDATE_TIMEOUT=10 \
            uv run --quiet --with websockets python "$ws_script" \
            > /tmp/exer_ws_log 2>&1; then
            pass "WS subscribe→update→unsubscribe round-trip on ${chosen} (CRUD-added)"
        else
            tail -20 /tmp/exer_ws_log | sed 's/^/    /'
            fail "WS exerciser failed against CRUD-added PV ${chosen}"
        fi
    else
        note "WS round-trip skipped (uv not found or direct_control_ws.py missing)"
    fi
fi

# ─── 5. Export the registry ─────────────────────────────────────────────
step "Export registry"

mkdir -p "$WORK_DIR"
status=$(req GET "${CONFIG_URL}/api/v1/registry/export")
expect_status 200 "$status" "/api/v1/registry/export"
cp /tmp/exer_body "$WORK_DIR/happi_db.json"
exported_count=$(jq 'length' < "$WORK_DIR/happi_db.json")
[ "$exported_count" = "$expected_count" ] \
    || fail "exported $exported_count entries, expected $expected_count"
pass "exported ${exported_count} entries to ${WORK_DIR}/happi_db.json"

# ─── 6. Validate happi-format shape on every entry ──────────────────────
step "Validate happi-format on every exported entry"

# Required fields in a happi entry: _id, name, device_class, args, kwargs, type, active
missing=$(jq -r '
    to_entries | .[] |
    select(
        (.value._id == null) or
        (.value.name == null) or
        (.value.device_class == null) or
        (.value.args == null) or
        (.value.kwargs == null) or
        (.value.type == null) or
        (.value.active == null)
    ) | .key
' < "$WORK_DIR/happi_db.json")
if [ -n "$missing" ]; then
    fail "exported entries missing required happi fields: $(echo $missing | tr '\n' ' ')"
fi
pass "every exported entry has _id, name, device_class, args, kwargs, type, active"

# Confirm both happi-seeded AND CRUD-added are in the export
for name in beam_current spot motor1 thermo random_walk_x; do
    if ! jq -e --arg n "$name" 'has($n)' < "$WORK_DIR/happi_db.json" > /dev/null; then
        fail "export missing entry for $name"
    fi
done
pass "spot-checked export contains both happi-seeded (beam_current, spot) and CRUD-added (motor1, thermo, random_walk_x)"

# ─── 7. Round-trip: re-import into a temp config-service ────────────────
step "Round-trip the export through a temp config-service"

if ! docker ps >/dev/null 2>&1; then
    fail "docker not accessible — re-run as 'sg docker -c $0' or after a fresh login"
fi

# Discover an image to use — any running config-service container's image works
running_image=$(docker ps --format '{{.Image}}' \
    --filter 'name=configuration_service' | head -1)
if [ -z "$running_image" ]; then
    fail "no running configuration_service container found; bring up a pod first"
fi
note "using image: ${running_image}"

# Make sure the side port isn't already taken
if docker ps --format '{{.Names}}' | grep -qx "$SIDE_NAME"; then
    docker kill "$SIDE_NAME" >/dev/null 2>&1 || true
fi

docker run --rm -d \
    --name "$SIDE_NAME" \
    -p "${SIDE_PORT}:8004" \
    -e CONFIG_LOAD_STRATEGY=happi \
    -e CONFIG_PROFILE_PATH=/profile \
    -e CONFIG_DB_PATH=/tmp/cs.db \
    -v "${WORK_DIR}:/profile:ro" \
    "$running_image" >/dev/null

deadline=$(( $(date +%s) + SIDE_HEALTH_TIMEOUT ))
while ! curl -sf "http://localhost:${SIDE_PORT}/health" >/dev/null; do
    if [ $(date +%s) -gt $deadline ]; then
        printf "    side container logs:\n"
        docker logs "$SIDE_NAME" 2>&1 | tail -20 | sed 's/^/      /'
        fail "side container didn't become healthy within ${SIDE_HEALTH_TIMEOUT}s"
    fi
    sleep 1
done
pass "side container ${SIDE_NAME} healthy on port ${SIDE_PORT}"

# Compare counts
side_count=$(curl -sf "http://localhost:${SIDE_PORT}/health" | jq -r '.devices_loaded')
[ "$side_count" = "$expected_count" ] \
    || fail "side count ${side_count} != expected ${expected_count}"
pass "side container loaded ${side_count} devices from re-imported export"

# Compare names
mapfile -t side_names < <(curl -sf "http://localhost:${SIDE_PORT}/api/v1/devices" \
    | jq -r '.[]? // keys[]' | sort)
side_names_str=$(IFS=' '; echo "${side_names[*]}")
mapfile -t orig_names < <(curl -sf "${CONFIG_URL}/api/v1/devices" \
    | jq -r '.[]? // keys[]' | sort)
orig_names_str=$(IFS=' '; echo "${orig_names[*]}")
if [ "$side_names_str" != "$orig_names_str" ]; then
    fail "side names differ from original. only-on-orig: $(comm -23 <(printf '%s\n' "${orig_names[@]}") <(printf '%s\n' "${side_names[@]}")). only-on-side: $(comm -13 <(printf '%s\n' "${orig_names[@]}") <(printf '%s\n' "${side_names[@]}"))"
fi
pass "side container's device-name set matches the original exactly"

# ─── Done ────────────────────────────────────────────────────────────────
printf "\n${GREEN}${BOLD}registry_roundtrip: ALL CHECKS PASSED${RESET}\n"
printf "  initial happi seed   : %d devices\n" "$initial_count"
printf "  CRUD-added at runtime: %d devices\n" "${#ADDED_DEVICES[@]}"
printf "  exported total       : %d devices\n" "$exported_count"
printf "  re-imported total    : %d devices\n" "$side_count"
