#!/bin/bash
# Start the COMBINED IOS demo: queueserver-repro stack (queueserver, tiled,
# simulated beamline IOCs) + the backend services pod (configuration,
# direct_control, presets).
#
# There is exactly ONE simulated beamline in this flow: the repro's loopback
# caproto IOCs. direct_control joins it via the docker-compose-backend.unified.yaml
# overlay (host network, loopback CA address list), so a value written from the
# UI's Apply button is the same PV a queued plan reads. The pod's own IOC
# containers are NOT started here — they exist for the standalone, UI-only
# compose flows that run without the queueserver stack.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose-backend.yaml"
UNIFIED_OVERLAY="$SCRIPT_DIR/docker-compose-backend.unified.yaml"
QS_REPRO_DIR="$SCRIPT_DIR/../../queueserver-repro"

echo "==> Starting the queueserver-repro stack (beamline IOCs, queueserver, tiled)..."
cd "$QS_REPRO_DIR"
./reproduce.sh up

echo ""
echo "==> Starting backend services (configuration, direct_control, presets)..."
# --no-deps: the IOC-container healthcheck dependencies don't apply here —
# the beamline is the repro's loopback IOCs, already up.
podman-compose -f "$COMPOSE_FILE" -f "$UNIFIED_OVERLAY" up -d --no-deps \
    configuration_service direct_control_service presets_service

echo ""
echo "=========================================="
echo "All services running:"
echo "=========================================="
echo "Backend services:"
echo "  - Configuration service:  http://localhost:8004"
echo "  - Direct control service: http://localhost:8003"
echo "  - Presets service:        http://localhost:8005"
echo ""
echo "Queueserver stack (host):"
echo "  - HTTP API:   http://localhost:60610  (Swagger UI at /docs)"
echo "  - Tiled API:  http://localhost:8000"
echo "  - Simulated beamline: repro loopback IOCs (shared by UI writes AND plans)"

if [ -f "$HOME/qs-repro/config/secrets.env" ]; then
    API_KEY=$(grep -oP 'HTTP_API_KEY=\K.*' "$HOME/qs-repro/config/secrets.env" 2>/dev/null || echo "<not found>")
    echo "  - API key:    $API_KEY"
else
    echo "  - API key:    (check ~/qs-repro/config/secrets.env)"
fi

echo ""
echo "=========================================="
echo "Frontend setup:"
echo "=========================================="
echo "The only variable the frontend reads today is VITE_API_URL"
echo "(direct-control base; its built-in default already matches this stack):"
echo "  VITE_API_URL=http://localhost:8003/api/v1"
echo ""
echo "Queueserver/Tiled URLs + API key wiring is pending in the frontend —"
echo "see frontend/.env.example for the canonical variable names."
echo ""
echo "=========================================="
echo "To stop all services:"
echo "=========================================="
echo "  ./stop-all.sh"
echo ""
