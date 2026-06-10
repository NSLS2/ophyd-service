# IOS Beamline Profile Collection — Reference

> **Purpose**: Knowledge reference for the legacy **`ios-profile-collection`** that this
> `ophyd-service` repository modernizes. The profile collection is the historical
> source-of-truth for the NSLS-II **IOS** (Inelastic Optics Scattering) beamline.
>
> **On-disk location** (developer machine): `~/Desktop/ios-profile-collection`
> — a *sibling* of this `ophyd-service` workspace, **not** committed inside it.
> **Upstream**: <https://github.com/NSLS-II-IOS/ios-profile-collection>

---

## Why this matters to `ophyd-service`

| Legacy profile-collection artifact | Modern `ophyd-service` counterpart |
|---|---|
| `startup/edge_map.json` | `presets_service` **edge-map** table |
| Scan params in multi-spectra framework / `98-ramp.py` | `presets_service` **scan-presets** table |
| Detector settings (commented `DET_SETTINGS` in `99-settings.py`) | `presets_service` **detector-presets** table |
| Ophyd device classes in `startup/*.py` | `configuration_service` device registry (happi) |
| Live IOCs (PGM, EPU, scaler, vortex…) | Simulated caproto IOCs in `integration/ioc/` |
| Beamline happi DB | `integration/happi/sites/ios/happi_db.json` |

> Note: **detector presets** (sample gains/decades, vortex thresholds) are **not** in
> `edge_map.json` upstream — they live in a commented `DET_SETTINGS` dict in
> `99-settings.py`. Useful if seeding realistic detector-preset data.

---

## 1. Profile organization & startup order

Scripts in `startup/` load lexicographically (`00` → `99`).

| File | Role |
|---|---|
| `00-startup.py` | Base `nslsii` config (broker=`ios`, Kafka→redis at `xf23id2-ios-redis1.nsls2.bnl.gov:6380`), disables BEC plots, pyOlog logbook, metadata defaults (`beamline_id='IOS'`). |
| `01-classes.py` | Ophyd device class defs; defines **`Vortex`** (`EpicsMCA` + `EpicsDXP`). |
| `10-machine.py` | Undulator (`EPU1`, `EPU2`) + PGM feedback-loop control. |
| `10-optics.py` | **PGM (VLS-PGM) monochromator**, mirrors (M1A, M1B, M3B w/ feedback), slits. |
| `11-valves.py` | Valve signals + `TwoButtonShutter` classes. |
| `20-detectors.py` | **Scaler** (`DodgyEpicsScaler`), **Vortex**, ring current, normalization. |
| `21-specs_analyzer.py` | SPECS photoelectron analyzer (`SpecsDetectorCam`, HDF5). |
| `22-xspress3.py` | **Xspress3** fluorescence detector (1 channel, 4 MCArois). |
| `23-devices.py` | SPECS sputter gun, degas, helpers. |
| `47-IOS_gui.py` | `bsstudio` GUI loader (`ios_gui.ui`). |
| `50-scans.py` | Deprecated scan setup (comments only). |
| `94-multi_spectra.py` | **Multi-spectra scan framework** (`ios_multiscan_plan_factory`). |
| `95-analysis.py` | Plotting (`plot_norm_*`), MCA spectrum saving. |
| `96-custom.py` | Alignment scans (BDC z-scans, KB roll/pitch). |
| `97-misc.py` | User check-in/out, CSV export (`save_xas_csv`, `save_all`). |
| `98-ramp.py` | **Energy ramp plans** (`E_ramp`) — PGM fly-scan + EPU feedback coordination. |
| `99-settings.py` | Shutter suspenders (FE/DS), `multi_part_ascan`, `open_all_valves`. |

---

## 2. Core devices & PV prefixes

**Beamline prefix**: `XF:23ID` (front-end/common), `XF:23ID2` (downstream optics/detectors).

### Monochromator (PGM)
- **Class**: `PGM` (nested `PGMEnergy`, `MonoFly`) — instance `pgm = PGM('XF:23ID2-OP{Mono', name='pgm')`; alias `pgm_energy = pgm.energy`.
- `energy`: readback `}Enrgy-I`, setpoint `}Enrgy-SP` (200–2200 eV).
- `fly` (`MonoFly`): `start_sig`, `stop_sig`, `velocity`, `fly_start`/`fly_stop`, `scan_status`.
- Method `reset_fbl(energy, epu_lookup_table, epu_input_offset, fbl_setpoint)` — resets M1B feedback loop.

### Mirrors
- **M1A** `Mirror` @ `XF:23IDA-OP:1{Mir:1` (z, y, x, pit, yaw, rol)
- **M1B1** `M1bMirror` @ `XF:23IDA-OP:2{Mir:1A` (adds `FBL` feedback loop)
- **M3B** `Mirror` @ `XF:23ID2-OP{Mir:3B`
- `FeedbackLoop`: enable, setpoint, requested/actual value, error, output, limits, delta_t, deadband.

### Undulator (EPU)
- **Classes**: `EPU1`, `EPU2` @ `XF:23ID-ID{EPU:1` / `EPU:2`.
- `gap`, `phase`: `PVPositionerPC` (readback `Pos-I`, setpoint `Pos-SP`).
- `flt`/`rlt` (`Interpolator`): front/rear-left-table — input, input_offset, input_link, output, deadband.
- `table`: selection signal `}Val:Table-Sel`.

### Slits
- `slt1 = SlitsGapCenter('XF:23ID2-OP{Slt:1', ...)` → xg, xc, yg, yc.
- `slt2 = EpicsMotor('XF:23ID2-OP{Slt:2-Ax:Y}Mtr', ...)`.

---

## 3. Detectors

### Scaler (SynApps)
- **Class**: `DodgyEpicsScaler` @ `XF:23ID2-ES{Sclr:1}` — instance `sclr`.
- Read/hinted: `chan2`, `chan3`, `chan4`. Also `ring_curr` (`XF:23ID-SR{}I-I`), `norm_ch4`, `sclr_time`.

### Vortex (energy-dispersive fluorescence)
- **Class**: `Vortex` (`EpicsMCA` + `EpicsDXP`) @ `XF:23ID2-ES{Vortex}` — instance `vortex`.
- `mca`: spectrum, `roi0`–`roi4`, preset_real/live_time. `vortex`: energy_threshold, peaking_time.
- **ROI4 = PFY**, **ROI3 = IPFY** (hinted for live feedback).

### Xspress3 (multi-element fluorescence)
- PV prefix `XF:23ID2-ES{Xsp:1}:` — instance `xs3`. 1 channel, 4 MCArois (`roi1`–`roi4`).
- HDF5 single-file-per-trigger, key `/entry/data/data`, path `/nsls2/data3/ios/legacy/xspress3_data/%Y/%m/%d/`.

### SPECS analyzer (photoelectron spectroscopy)
- **Cam**: `SpecsDetectorCam`; **detector**: `SpecsHDF5Plugin` (`FileStoreHDF5SingleIterativeWrite`).
- Energy PVs: `PASS_ENERGY`, `LOW_ENERGY`, `HIGH_ENERGY`, `KINETIC_ENERGY`, `STEP_SIZE`, `SAMPLES`.
- Config: `SCAN_RANGE`, `ACQ_MODE`, `DEFINE_SPECTRUM`, `VALIDATE_SPECTRUM`. HDF5 key `/entry/data/data`.

---

## 4. Edge map (`startup/edge_map.json`)

Flat JSON dict keyed by **element edge name** (`"Ni_L"`, `"O_K"`, …). Each entry:

```json
{
  "start": 520.0,      // start energy (eV)
  "stop": 560.0,       // stop energy (eV)
  "velocity": 0.05,    // fly-scan velocity (eV/s)
  "deadband": 5,       // EPU output deadband
  "epu_table": 6       // lookup table number
}
```

**Sample edges (18 total)**:

| Edge | start | stop | velocity | epu_table | deadband |
|---|---|---|---|---|---|
| O_K | 520 | 560 | 0.05 | 6 | 5 |
| Ni_L | 845 | 885 | 0.2 | 4 | 12 |
| Ce_M | 870 | 920 | 0.1 | 4 | 8 |
| Co_L / Co_L2 | 770 | 810 | 0.1 | 4 | 6 |
| Al_K | 1552 | 1592 | 0.3 | 10 | 4 |
| Si_K | 1840 | 1880 | 0.5 | 10 | 8 |
| Rh_L | 1530 | 1680 | 0.55 | 10 | 8 |

Used by `pgm.reset_fbl()` and energy-ramp plans to map spectroscopic edges to
beamline-optimized fly-scan parameters.

---

## 5. Scan plans & multi-spectra framework

### Energy ramp — `98-ramp.py`
`E_ramp(dets, start, stop, velocity, time=None, streamname='primary', deadband=8, md=None)`

1. Move PGM energy to `start`.
2. Set fly-scan limits (`start_sig`, `stop_sig`, `velocity`).
3. Stage detector(s) (SPECS, Xspress3).
4. Save/change EPU interpolator deadband.
5. Link EPU input → PGM readback (`pgm_energy.readback.pvname`).
6. Trigger fly-scan (`pgm.fly.fly_start = 1`).
7. Wait `pgm.fly.scan_status → 'Ready'`; collect points during ramp.
8. Clean up: reset energy setpoint, restore EPU link, reset deadband.

### Multi-spectra factory — `94-multi_spectra.py`
`ios_multiscan_plan_factory_wrapper(scans)` → `ios_multiscan_plan_factory(scans)`

- Input: list of `(scan_name, parameters, settings)` tuples.
- `parameters` keys: `plan` (`scan`/`grid_scan`/`ios_count`/`count`), `arguments` (device refs + positions), `detectors`, `spectra_type`, `interesting_spectra`, `num_groups`.
- `settings`: dict mapping device-ref strings → values (motor positions).
- Resolves string refs to ophyd objects (`_str_to_obj()`), moves to initial settings (`_move_from_dict()`), runs the selected plan; per-step fn loops over `num_groups` × `interesting_spectra`.

### Helpers
- `change_epu_flt_link(new_target)`, `open_all_valves(valve_list)`, `multi_part_ascan(...)`, `NormPlot` (LivePlot of `sclr_ch4/sclr_ch3`).

---

## 6. Valves & shutters — `11-valves.py`
- Gate valves: `valve_diag3`, `valve_mir`, `valve_slt3`, `valve_slt1`, `valve_pmp1/2`, `valve_mono`, `valve_diag1`, `valve_appes`.
- Shutters (`TwoButtonShutter`): FE `XF:23ID-PPS{Sh:FE}Pos-Sts`, DS `XF:23ID2-PPS{PSh}Pos-Sts` — installed as RE suspenders.

---

## 7. GUI / analysis / export
- **GUI** (`47-IOS_gui.py`): `bsstudio` Qt loader of `ios_gui.ui`.
- **Analysis** (`95-analysis.py`): `plot_norm_trans/tey/pfy`, `plot_raw_pfy/ipfy`; normalize by scaler ch3/ch4 or ring current.
- **Export** (`97-misc.py`): `user_checkin()`, `save_xas_csv()` (normal/PD/es/PEY/stability), `save_bdc()`, `save_all()`.
- **Alignment** (`96-custom.py`): `bdc_z_scan_*()`, `test_kbx_corr()`.

---

## 8. Dependencies (`pixi.toml`)
- **Env**: linux-64, Python `>=3.12,<3.13`.
- **Bluesky**: `bluesky-base==1.15.0`, `bluesky-queueserver`, `bluesky-tiled-plugins==2.0.2`.
- **Ophyd**: `ophyd>=1.11.0`, `ophyd-async>=0.13.7,<0.14`.
- **NSLS-II**: `nslsii==0.11.8`, `tiled-client==0.2.9`, `databroker==2.0.0`.
- **EPICS**: `pyepics`, `epicscorelibs>=7.0.7.99.1.1`, `pvxslibs>=1.3.2`.
- **Tasks**: `profile` (setup), `terminal` (`ipython --profile-dir=.`, MPLBACKEND=qtagg), `qs` (queue-server: re-manager + http-server).

---

## 9. PV naming convention summary
| Token | Subsystem |
|---|---|
| `{Mono}` | Monochromator (PGM) |
| `{Mir:1A}`, `{Mir:3B}` | Mirrors |
| `{EPU:1}`, `{EPU:2}` | Undulator units |
| `{Slt:1}`, `{Slt:2}` | Slits |
| `{Sclr:1}` | Scaler |
| `{Vortex}` | Vortex MCA |
| `{Xsp:1}` | Xspress3 |
| `{SPECS-PS1}` | SPECS sputter PS |
| `{Sh:FE}`, `{PSh}` | FE / downstream shutters |

---

## 10. Key integration insights
1. `edge_map.json` → `presets_service` **edge-map** (start/stop/velocity/deadband/epu_table per edge).
2. Detector presets vary by edge but are **not** in `edge_map.json` upstream (commented `DET_SETTINGS` in `99-settings.py`).
3. Scan params (energy range, velocity, EPU table, deadband, detector list, counts) abstracted in the multi-spectra framework → map to **scan-presets**.
4. Device naming is consistent (`pgm.energy`, `epu1.gap`, `vortex.mca.rois`, `xs3`, `sclr`) — usable as preset references.
5. **Fly-scan coordination** (PGM energy ramp + EPU interpolator link + detector staging) is the core beamline operation `ophyd-service` must preserve.
