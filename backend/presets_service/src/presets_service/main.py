"""
Presets Service — FastAPI Application

Beamline-specific edge preset storage.  Replaces the det_settings.xlsx
and scan_parameters.xlsx files with a SQLite-backed CRUD API.

Read endpoints are open to all users.
Write endpoints (POST/PUT/DELETE) should be gated behind admin auth
at the reverse-proxy / middleware layer.
"""

from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from .models import (
    DetectorPresetCreate,
    DetectorPresetEntry,
    DetectorPresetUpdate,
    EdgeFullPreset,
    ScanPresetCreate,
    ScanPresetEntry,
    ScanPresetUpdate,
)
from .settings import Settings
from .store import PresetsStore

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger()

# ── helpers ────────────────────────────────────────────────────────

_TABLE_CONFIGS: dict[str, dict[str, Any]] = {
    "scan-presets": {
        "table": "scan_presets",
        "create_model": ScanPresetCreate,
        "update_model": ScanPresetUpdate,
        "entry_model": ScanPresetEntry,
    },
    "detector-presets": {
        "table": "detector_presets",
        "create_model": DetectorPresetCreate,
        "update_model": DetectorPresetUpdate,
        "entry_model": DetectorPresetEntry,
    },
}


def _get_or_404(store: PresetsStore, table: str, edge_index: str) -> dict:
    row = store.get(table, edge_index)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{edge_index} not found in {table}")
    return row


# ── app factory ────────────────────────────────────────────────────


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = Settings()

    store = PresetsStore(settings.db_path)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        store.initialize()
        if settings.seed_path and settings.seed_path.is_dir():
            # Seed each table only if it's currently empty.
            for table in ("scan_presets", "detector_presets"):
                if store.is_empty(table):
                    store.seed_from_directory(settings.seed_path)
                    break  # seed_from_directory loads all files at once
        logger.info("presets_service ready", db_path=str(settings.db_path))
        yield

    app = FastAPI(
        title="Presets Service",
        description="Per-beamline edge preset storage",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── health ─────────────────────────────────────────────────────

    @app.get("/health")
    def health():
        return {"status": "ok"}

    # ── per-table CRUD (3 tables × 5 endpoints = 15) ──────────────

    for url_slug, cfg in _TABLE_CONFIGS.items():
        _table = cfg["table"]
        _CreateModel = cfg["create_model"]
        _UpdateModel = cfg["update_model"]
        _EntryModel = cfg["entry_model"]

        def _make_routes(table: str, CreateModel: type, UpdateModel: type, EntryModel: type, slug: str):
            @app.get(
                f"/api/v1/{slug}",
                response_model=list[EntryModel],
                tags=[slug],
            )
            def list_all():
                return store.list_all(table)

            @app.get(
                f"/api/v1/{slug}/{{edge_index}}",
                response_model=EntryModel,
                tags=[slug],
            )
            def get_one(edge_index: str):
                return _get_or_404(store, table, edge_index)

            @app.post(
                f"/api/v1/{slug}",
                response_model=EntryModel,
                status_code=status.HTTP_201_CREATED,
                tags=[slug],
            )
            def create(body: CreateModel):
                existing = store.get(table, body.edge_index)
                if existing is not None:
                    raise HTTPException(
                        status.HTTP_409_CONFLICT,
                        f"{body.edge_index} already exists in {table}",
                    )
                data = body.model_dump()
                edge_index = data.pop("edge_index")
                store.upsert(table, edge_index, data)
                return store.get(table, edge_index)

            @app.put(
                f"/api/v1/{slug}/{{edge_index}}",
                response_model=EntryModel,
                tags=[slug],
            )
            def upsert(edge_index: str, body: UpdateModel):
                existing = store.get(table, edge_index)
                if existing is None:
                    raise HTTPException(
                        status.HTTP_404_NOT_FOUND,
                        f"{edge_index} not found in {table}",
                    )
                updates = body.model_dump(exclude_unset=True)
                merged = {**existing, **updates}
                merged.pop("edge_index", None)
                store.upsert(table, edge_index, merged)
                return store.get(table, edge_index)

            @app.delete(
                f"/api/v1/{slug}/{{edge_index}}",
                status_code=status.HTTP_200_OK,
                tags=[slug],
            )
            def delete(edge_index: str):
                if not store.delete(table, edge_index):
                    raise HTTPException(
                        status.HTTP_404_NOT_FOUND,
                        f"{edge_index} not found in {table}",
                    )
                return {"deleted": edge_index}

        _make_routes(_table, _CreateModel, _UpdateModel, _EntryModel, url_slug)

    # ── combined view ──────────────────────────────────────────────

    @app.get(
        "/api/v1/edges/{edge_index}/full",
        response_model=EdgeFullPreset,
        tags=["edges"],
    )
    def get_full_preset(edge_index: str):
        sc = store.get("scan_presets", edge_index)
        dt = store.get("detector_presets", edge_index)
        if sc is None and dt is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"No presets found for {edge_index}",
            )
        # Strip edge_index from sub-dicts (the response model has it at top level)
        def _strip(d: dict | None) -> dict | None:
            if d is None:
                return None
            d = dict(d)
            d.pop("edge_index", None)
            return d

        return EdgeFullPreset(
            edge_index=edge_index,
            scan=_strip(sc),
            detector=_strip(dt),
        )

    return app


app = create_app()
