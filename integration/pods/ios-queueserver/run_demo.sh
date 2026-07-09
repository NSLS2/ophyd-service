#!/usr/bin/env bash
#
# IOS queueserver demo launcher.
#
# Build the pod, bring it up, open the RE Manager environment (which imports the
# IOS profile collection), and verify the bluesky-httpserver serves the profile's
# plans and devices — the endpoints the frontend consumes.
#
# Usage:
#   ./run_demo.sh                 # build + up + open env + verify (default)
#   ./run_demo.sh --rebuild       # force --build
#   ./run_demo.sh --skip-verify   # just up + open the environment
#   ./run_demo.sh --tear-down     # verify then `down -v`
#   ./run_demo.sh --help
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE="${SCRIPT_DIR}/docker-compose.yaml"
HTTP="http://localhost:60610"
# Must match QSERVER_HTTP_SERVER_SINGLE_USER_API_KEY in docker-compose.yaml.
APIKEY="iosdemosecretkey0123456789"
AUTH=(-H "Authorization: ApiKey ${APIKEY}")

if [ -t 1 ]; then
    GREEN=$'\033[32m'; YELLOW=$'\033[33m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
else
    GREEN=''; YELLOW=''; BOLD=''; RESET=''
fi
step() { printf "\n${BOLD}== %s ==${RESET}\n" "$1"; }
note() { printf "  ${YELLOW}%s${RESET}\n" "$1"; }
ok()   { printf "  ${GREEN}%s${RESET}\n" "$1"; }

REBUILD=0; VERIFY=1; TEAR_DOWN=0
for arg in "$@"; do
    case "$arg" in
        --rebuild)     REBUILD=1 ;;
        --skip-verify) VERIFY=0 ;;
        --tear-down)   TEAR_DOWN=1 ;;
        -h|--help)     sed -n '2,14p' "$0" | sed 's/^# \?//'; exit 0 ;;
        *) echo "unknown arg: $arg (try --help)" >&2; exit 2 ;;
    esac
done

command -v docker >/dev/null || { echo "docker not on PATH" >&2; exit 1; }

step "Build + up (redis, mongo, blackhole IOC, queueserver, httpserver)"
build_flag=""; [ "$REBUILD" = "1" ] && build_flag="--build"
# `up -d` waits on depends_on service_healthy; queueserver becomes healthy only
# after its ZMQ control socket answers, i.e. after the manager is fully started.
docker compose -f "$COMPOSE" up -d $build_flag
ok "pod up"

step "Waiting for httpserver ($HTTP)"
deadline=$(( $(date +%s) + 120 ))
until curl -sf -o /dev/null "${AUTH[@]}" "${HTTP}/api/status"; do
    if [ "$(date +%s)" -gt "$deadline" ]; then
        note "timeout waiting for httpserver"
        docker compose -f "$COMPOSE" ps
        exit 1
    fi
    sleep 1
done
ok "httpserver ready"

step "Opening RE Manager environment (imports the IOS profile)"
curl -sf "${AUTH[@]}" -X POST "${HTTP}/api/environment/open" >/dev/null
note "environment opening — importing startup/*.py can take ~30-60s"
deadline=$(( $(date +%s) + 180 ))
while :; do
    st=$(curl -sf "${AUTH[@]}" "${HTTP}/api/status")
    exists=$(printf '%s' "$st" | python3 -c "import sys,json;print(json.load(sys.stdin).get('worker_environment_exists'))" 2>/dev/null || echo None)
    state=$(printf '%s' "$st" | python3 -c "import sys,json;print(json.load(sys.stdin).get('worker_environment_state'))" 2>/dev/null || echo None)
    [ "$exists" = "True" ] && [ "$state" = "idle" ] && { ok "environment open"; break; }
    if [ "$(date +%s)" -gt "$deadline" ]; then
        note "timeout opening environment. Recent manager logs:"
        docker compose -f "$COMPOSE" logs --tail 40 queueserver
        exit 1
    fi
    sleep 3
done

if [ "$VERIFY" = "1" ]; then
    step "Verifying the profile loaded (plans + devices over HTTP)"
    plans=$(curl -sf "${AUTH[@]}" "${HTTP}/api/plans/allowed" \
        | python3 -c "import sys,json;print(len(json.load(sys.stdin).get('plans_allowed',{})))")
    devices=$(curl -sf "${AUTH[@]}" "${HTTP}/api/devices/allowed" \
        | python3 -c "import sys,json;print(len(json.load(sys.stdin).get('devices_allowed',{})))")
    ok "allowed plans:   ${plans}"
    ok "allowed devices: ${devices}"
    if [ "$plans" -gt 0 ] && [ "$devices" -gt 0 ]; then
        ok "IOS profile opened successfully under bluesky-queueserver"
    else
        note "environment is open but no plans/devices were generated — check logs"
        exit 1
    fi
fi

if [ "$TEAR_DOWN" = "1" ]; then
    step "Tearing down (--tear-down)"
    docker compose -f "$COMPOSE" down -v
    ok "pod removed"
else
    cat <<EOF

${BOLD}Pod is up.${RESET} bluesky-httpserver: ${HTTP}
  API key (write ops):   ${APIKEY}   (Authorization: ApiKey <key>)
  Status:                curl -H "Authorization: ApiKey ${APIKEY}" ${HTTP}/api/status
  Allowed plans:         curl -H "Authorization: ApiKey ${APIKEY}" ${HTTP}/api/plans/allowed
  Allowed devices:       curl -H "Authorization: ApiKey ${APIKEY}" ${HTTP}/api/devices/allowed
Tear down: docker compose -f ${COMPOSE} down -v
EOF
fi
