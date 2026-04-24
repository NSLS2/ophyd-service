#!/usr/bin/env sh
# Generate TypeScript types from the OpenAPI schemas in $SCHEMA_DIR
# (default: ../shared-schema for local dev; /app/schema in the container).
#
# Runs once, then exits. Per the docker-compose setup, this runs before
# `vite` starts each time the frontend container launches.
set -eu

SCHEMA_DIR="${SCHEMA_DIR:-../shared-schema}"
OUT_DIR="$(dirname "$0")/../src/api"

mkdir -p "$OUT_DIR"

for svc in configuration_service direct_control; do
    src="$SCHEMA_DIR/${svc}.openapi.json"
    dst="$OUT_DIR/${svc}.d.ts"
    if [ ! -f "$src" ]; then
        echo "generate-types: $src missing; skipping. Start the backends first so they write to the shared-schema volume." >&2
        continue
    fi
    echo "generate-types: $src -> $dst"
    npx --yes openapi-typescript "$src" -o "$dst"
done
