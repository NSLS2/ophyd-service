"""
SQLite store for edge presets.

Two tables: scan_presets, detector_presets.
Thread-local connections, WAL mode, parameterized queries.
Same pattern as configuration_service's DeviceRegistryStore.
"""

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── SQL ────────────────────────────────────────────────────────────


_CREATE_SCAN_PRESETS = """
CREATE TABLE IF NOT EXISTS scan_presets (
    edge_index TEXT PRIMARY KEY,
    start      REAL NOT NULL,
    stop       REAL NOT NULL,
    velocity   REAL NOT NULL,
    deadband   REAL NOT NULL,
    epu1offset REAL NOT NULL,
    epu_table  INTEGER NOT NULL,
    scan_count INTEGER NOT NULL,
    intervals  REAL NOT NULL,
    au_mesh    REAL NOT NULL,
    e_align    REAL NOT NULL,
    m1b1_sp    REAL NOT NULL
)
"""

_CREATE_DETECTOR_PRESETS = """
CREATE TABLE IF NOT EXISTS detector_presets (
    edge_index    TEXT PRIMARY KEY,
    samplegain    TEXT NOT NULL,
    sampledecade  TEXT NOT NULL,
    aumeshgain    TEXT NOT NULL,
    aumeshdecade  TEXT NOT NULL,
    pd_gain       TEXT NOT NULL,
    pd_decade     TEXT NOT NULL,
    vortex_low    INTEGER NOT NULL,
    vortex_high   INTEGER NOT NULL,
    ipfy_low      INTEGER NOT NULL,
    ipfy_high     INTEGER NOT NULL,
    vortex_pos    REAL NOT NULL,
    vortex_time   REAL NOT NULL,
    sclr_time     REAL NOT NULL
)
"""

# Column names (excluding edge_index PK) for each table.
_SCAN_COLS = [
    "start", "stop", "velocity", "deadband", "epu1offset",
    "epu_table", "scan_count", "intervals", "au_mesh", "e_align", "m1b1_sp",
]
_DETECTOR_COLS = [
    "samplegain", "sampledecade", "aumeshgain", "aumeshdecade",
    "pd_gain", "pd_decade", "vortex_low", "vortex_high",
    "ipfy_low", "ipfy_high", "vortex_pos", "vortex_time", "sclr_time",
]

_TABLE_META: dict[str, list[str]] = {
    "scan_presets": _SCAN_COLS,
    "detector_presets": _DETECTOR_COLS,
}


class PresetsStore:
    """SQLite-backed preset storage."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._local = threading.local()
        self._initialized = False

    # ── connection ─────────────────────────────────────────────────

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0,
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    @contextmanager
    def _transaction(self):
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ── init ───────────────────────────────────────────────────────

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._transaction() as conn:
            conn.execute(_CREATE_SCAN_PRESETS)
            conn.execute(_CREATE_DETECTOR_PRESETS)
        self._initialized = True
        logger.info("PresetsStore initialized at %s", self.db_path)

    def is_empty(self, table: str) -> bool:
        conn = self._get_connection()
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608
        return row[0] == 0

    # ── generic CRUD ───────────────────────────────────────────────

    def list_all(self, table: str) -> list[dict[str, Any]]:
        cols = _TABLE_META[table]
        conn = self._get_connection()
        rows = conn.execute(
            f"SELECT edge_index, {', '.join(cols)} FROM {table} ORDER BY edge_index"  # noqa: S608
        ).fetchall()
        return [dict(r) for r in rows]

    def get(self, table: str, edge_index: str) -> dict[str, Any] | None:
        cols = _TABLE_META[table]
        conn = self._get_connection()
        row = conn.execute(
            f"SELECT edge_index, {', '.join(cols)} FROM {table} WHERE edge_index = ?",  # noqa: S608
            (edge_index,),
        ).fetchone()
        return dict(row) if row else None

    def upsert(self, table: str, edge_index: str, data: dict[str, Any]) -> None:
        cols = _TABLE_META[table]
        all_cols = ["edge_index"] + cols
        placeholders = ", ".join(["?"] * len(all_cols))
        values = [edge_index] + [data[c] for c in cols]
        with self._transaction() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO {table} ({', '.join(all_cols)}) VALUES ({placeholders})",  # noqa: S608
                values,
            )

    def delete(self, table: str, edge_index: str) -> bool:
        with self._transaction() as conn:
            cursor = conn.execute(
                f"DELETE FROM {table} WHERE edge_index = ?",  # noqa: S608
                (edge_index,),
            )
            return cursor.rowcount > 0

    # ── seed ───────────────────────────────────────────────────────

    def seed_table(self, table: str, entries: dict[str, dict[str, Any]]) -> int:
        """Bulk-load a dict of {edge_index: {col: val, ...}} into a table."""
        count = 0
        for edge_index, data in entries.items():
            self.upsert(table, edge_index, data)
            count += 1
        logger.info("Seeded %d entries into %s", count, table)
        return count

    def seed_from_directory(self, seed_dir: Path) -> None:
        """Load *_seed.json files from a directory.

        Expected filenames: scan_presets_seed.json,
        detector_presets_seed.json.  Each is a JSON object keyed by edge_index.
        """
        mapping = {
            "scan_presets_seed.json": "scan_presets",
            "detector_presets_seed.json": "detector_presets",
        }
        for filename, table in mapping.items():
            path = seed_dir / filename
            if path.exists():
                with open(path) as f:
                    entries = json.load(f)
                self.seed_table(table, entries)
