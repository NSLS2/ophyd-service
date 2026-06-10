# Presets Service

Beamline-specific edge preset storage. Replaces Excel-based `det_settings.xlsx`
and `scan_parameters.xlsx` with a SQLite-backed CRUD API.

## Quick start

```bash
pip install -e ".[dev]"
bluesky-presets-service          # starts on :8005
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/scan-presets` | List all scan presets |
| GET | `/api/v1/detector-presets` | List all detector presets |
| GET | `/api/v1/edges/{edge_index}/full` | Combined view |
| POST/PUT/DELETE | per-table CRUD | Admin-only writes |
| GET | `/health` | Health check |

## Configuration

All settings via `PRESETS_` env prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `PRESETS_HOST` | `0.0.0.0` | Bind address |
| `PRESETS_PORT` | `8005` | Port |
| `PRESETS_DB_PATH` | `/tmp/presets.db` | SQLite database path |
| `PRESETS_SEED_PATH` | — | Directory with `*_seed.json` files |
| `PRESETS_CORS_ORIGINS` | `["*"]` | CORS allowed origins |
