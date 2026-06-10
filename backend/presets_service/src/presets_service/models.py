"""Pydantic models for the Presets Service API."""

from typing import Optional

from pydantic import BaseModel


# ── Scan Presets (from scan_parameters.xlsx) ───────────────────────

class ScanPresetBase(BaseModel):
    start: float
    stop: float
    velocity: float
    deadband: float
    epu1offset: float
    epu_table: int
    scan_count: int
    intervals: float
    au_mesh: float
    e_align: float
    m1b1_sp: float


class ScanPresetCreate(ScanPresetBase):
    edge_index: str


class ScanPresetUpdate(BaseModel):
    start: Optional[float] = None
    stop: Optional[float] = None
    velocity: Optional[float] = None
    deadband: Optional[float] = None
    epu1offset: Optional[float] = None
    epu_table: Optional[int] = None
    scan_count: Optional[int] = None
    intervals: Optional[float] = None
    au_mesh: Optional[float] = None
    e_align: Optional[float] = None
    m1b1_sp: Optional[float] = None


class ScanPresetEntry(ScanPresetBase):
    edge_index: str


# ── Detector Presets (from det_settings.xlsx) ──────────────────────

class DetectorPresetBase(BaseModel):
    samplegain: str
    sampledecade: str
    aumeshgain: str
    aumeshdecade: str
    pd_gain: str
    pd_decade: str
    vortex_low: int
    vortex_high: int
    ipfy_low: int
    ipfy_high: int
    vortex_pos: float
    vortex_time: float
    sclr_time: float


class DetectorPresetCreate(DetectorPresetBase):
    edge_index: str


class DetectorPresetUpdate(BaseModel):
    samplegain: Optional[str] = None
    sampledecade: Optional[str] = None
    aumeshgain: Optional[str] = None
    aumeshdecade: Optional[str] = None
    pd_gain: Optional[str] = None
    pd_decade: Optional[str] = None
    vortex_low: Optional[int] = None
    vortex_high: Optional[int] = None
    ipfy_low: Optional[int] = None
    ipfy_high: Optional[int] = None
    vortex_pos: Optional[float] = None
    vortex_time: Optional[float] = None
    sclr_time: Optional[float] = None


class DetectorPresetEntry(DetectorPresetBase):
    edge_index: str


# ── Combined view (GET /api/v1/edges/{edge_index}/full) ────────────

class EdgeFullPreset(BaseModel):
    edge_index: str
    scan: Optional[ScanPresetBase] = None
    detector: Optional[DetectorPresetBase] = None
