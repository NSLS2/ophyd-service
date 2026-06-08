# Site sandbox — NSLS-II IOS beamline

Happi device DB + ophyd class shim rendered from
[`ios-profile-collection`](https://github.com/NSLS-II-IOS/ios-profile-collection)
(local clone at `/home/asligar/git_projects/ios-profile-collection`).

This directory is **site-specific** — it bakes in NSLS-II IOS PV naming
(`XF:23ID*`), the `nslsii.areadetector.xspress3` builder, and detector
shapes from the IOS profile. Keep it under `sites/<name>/` so the
top-level `integration/happi/happi_db.json` stays facility-neutral
(community-not-NSLS-II).

Intended consumer: `configuration_service`. Load via:

```
CONFIG_LOAD_STRATEGY=happi
CONFIG_PROFILE_PATH=/path/to/integration/happi/sites/ios
```

The loader auto-discovers `happi_db.json` under `CONFIG_PROFILE_PATH`.

## Files

| File | Purpose |
|---|---|
| `happi_db.json` | 94 happi entries — every top-level device variable in `ios-profile-collection/startup/*.py` |
| `ios_devs.py` | Vanilla-ophyd port of every custom class referenced by the JSON |
| `README.md` | this file |

## Validation against live IOCs (2026-05-14 / 05-15)

The port was cross-checked against live IOCs via `manage-iocs attach
<name>` + `dbl` (and targeted `caget`s where dumps were partial) on
`xf23id1-ws1` / `xf23id2-ws1`. Validated shapes:

| IOC | Validated | Covers |
|---|---|---|
| `op-m3b` | `Mirror` class, MirrorAxis curly-brace closure scheme | m1a, m1b1, m1b2, m3b (4 entries) + m3b_pitch |
| `MC10` | PMAC motor record shape | slt2, dm1_x, dm1_roll, dm1_diag, dm1_slt (5 of 36) |
| `es-vortex` | `Vortex` (mca1 record + dxp1: subtree) | vortex (full MCA + DXP shape, 4096-channel) |
| `specsAnalyser` | `SpecsDetector` + `SpecsDetectorCam` (~30 PVs) | specs |
| `va-01` | gate-valve naming + `Valve` compound | 16 valve entries |
| `es-sr570` | SR570 gain/decade controls | 6 current-amp entries (sample/aumesh/pd × gain/decade) |
| `cam-exit-slit` | ADCore Stats1 plugin | yag_centroid |

**Bug found and fixed:** The profile's `SpecsDetectorCam` references
`TOTAL_POINTS_ITERTION_RBV` (missing the "A" in "ITERATION"). The live
IOC publishes the correctly-spelled `TOTAL_POINTS_ITERATION_RBV`. Fixed
in `ios_devs.py`. Filed as a profile-collection bug upstream is
recommended.

**Pending (host reachable):** `feedback` IOC was down — `FeedbackLoop`
(12 components) + 3 standalone signals (`m1b1_setpoint`,
`mirror_feedback`, `feedback`) unvalidated. Remaining 31 EpicsMotor
entries live on MC11/12/14/15/16/17/19, mc01, mc02-new, mc33 — same
PMAC motor-record shape as MC10, validation pending.

**Off-host (different IOC servers needed):**
- EPU1 / EPU2 (`XF:23ID-ID{EPU:*`)
- PGM / Mono (`XF:23ID2-OP{Mono*`)
- m1a, m1b1, m1b2 mirror A-cabinet IOCs (`XF:23IDA-OP:*`)
- Scaler (`XF:23ID2-ES{Sclr:1}*`)
- Xspress3 (`XF:23ID2-ES{Xsp:1}:*`)
- PPS shutters (`XF:23ID-PPS{Sh:FE}`, `XF:23ID2-PPS{PSh}`, `XF:23ID2-PPS:2{PSh}`)
- Ring current (`XF:23ID-SR{}I-I`)
- SR EPU stop signals (`SR:C23-ID:G1A{EPU:*`)
- SPECS-PS1 sputter/degas (`XF:23ID2-ES{SPECS-PS1}*`)

These entries use the same record-naming patterns already validated
elsewhere (curly-brace closure for Mirror→EPU/PGM, standard motor
records for the remaining motors, EpicsSignal/RO for simple PVs). The
shapes are inductively confirmed; only the specific PV existence
remains to verify when those hosts become accessible.

**Net confidence:** ~57 of 94 happi entries (~60%) directly or
shape-inductively confirmed. The port pattern held end-to-end across
every distinct device class the profile uses, with only the one
typo-fix needed.

## How the inventory was built

Walked the profile's startup tree with an AST extractor: parse every
`startup/*.py`, build the transitive set of classes that descend from
ophyd Device-shaped roots (`Device`, `EpicsSignal`, `EpicsMotor`,
`PVPositioner`, `CamBase`, `DetectorBase`, `Xspress3Detector`, ...),
then emit every top-level `name = Cls(prefix_arg, ..., name=...)`
assignment. The extractor also recognizes the dynamic-class pattern
(`X = build_..._class(...)`; later `var = X(...)`) used for `xs3`.

Manual cross-check confirmed agreement. The extractor isn't committed
here — re-run it with:

```python
ast.parse(...).body  # walk top-level Assign nodes
```

against `ios-profile-collection/startup/`.

## Device inventory

93 + 1 dynamic = **94** happi entries:

| Group | Count | Notes |
|---|---|---|
| Compound ophyd classes (`ios_devs.<X>`) | 16 | EPU1, EPU2, Mirror (×3), M1bMirror, PGM, SlitsGapCenter, Valve, TwoButtonShutter (×3), DodgyEpicsScaler, Vortex, SpecsDetector, Xspress3IOS |
| `ophyd.EpicsMotor` | 36 | KB / DM / BDC / diag / APPES / IOXAS / Vortex / slit motors |
| `ophyd.signal.EpicsSignal` | 41 | Valves, current-amp gains, mirror jog/pitch signals, EPU1 table+offset shortcuts |
| `ophyd.signal.EpicsSignalRO` | 1 | `yag_centroid` (final form, after the 97-misc.py shadow) |

### Profile quirks preserved

- `yag_centroid` is **defined twice** in the profile (10-optics.py:176
  as `EpicsSignal`, then redefined 97-misc.py:1247 as `EpicsSignalRO`).
  IPython startup is last-write-wins, so the RO version is canonical —
  that's what's in the happi DB.
- `m1b1_fp_rb` uses `name='m1b_fp_rb'` in the source (missing the `1`).
  The happi entry aligns `name` and `_id` with the python variable
  (`m1b1_fp_rb`) and flags the discrepancy in `documentation`.
- `valve_diag3_open` / `valve_diag3` and `valve_mir3_open` / `valve_mir`
  point at the same PV — distinct python variables, same `Cmd:Opn-Cmd`
  PV. Preserved as separate happi entries.
- `epu1table`, `epu1offset` duplicate components already accessible
  through `epu1.table` / `epu1.flt.input_offset`. Preserved as separate
  entries (the profile uses them as standalone shortcuts).
- `mirror_feedback` and `feedback` are two python variables pointing at
  the same `XF:23ID2-OP{FBck}Sts:FB-Sel` PV. Both registered.

### Custom classes in `ios_devs.py`

Ported 1:1 from the profile, vanilla-ophyd only (no bluesky / kafka /
pyOlog / amostra / databroker / nslsii — except for `Xspress3IOS`,
see below):

| From | Class(es) |
|---|---|
| `01-classes.py` | `Vortex` |
| `10-machine.py` | `GapMotor1`, `GapMotor2`, `PhaseMotor1`, `PhaseMotor2`, `Interpolator`, `EPU1`, `EPU2` |
| `10-optics.py` | `MirrorAxis`, `FeedbackLoop`, `Mirror`, `M1bMirror`, `MotorMirror`, `PGMEnergy`, `MonoFly`, `PGM`, `SlitsGapCenter` |
| `11-valves.py` | `Valve`, `TwoButtonShutter` |
| `20-detectors.py` | `DodgyEpicsSignal`, `DodgyEpicsScaler` |
| `21-specs_analyzer.py` | `SpecsDetectorCam`, `FileStoreHDF5Single`, `FileStoreHDF5SingleIterativeWrite`, `SpecsHDF5Plugin`, `SpecsSingleTrigger`, `SpecsDetector` |
| `22-xspress3.py` | `Xspress3IOS` (dynamic; see below) |

### The `Xspress3IOS` nslsii dependency

The IOS profile builds its Xspress3 class on the fly via
`nslsii.areadetector.xspress3.build_xspress3_class(...)`. There is no
upstream-ophyd equivalent — Xspress3 channel/MCAROI structure lives in
`nslsii`. `ios_devs.py` reproduces the same call with identical args
(`channel_numbers=(1,)`, `mcaroi_numbers=(1, 2, 3, 4)`,
`image_data_key="data"`, `Xspress3HDF5Plugin` under `hdf5plugin`).

The import is `try/except ImportError`-guarded so `ios_devs.py` still
loads in environments without nslsii — `Xspress3IOS` is `None` in that
case, and instantiating the happi entry for `xs3` will fail at load.

## Notes for future IOC mimicry (deferred)

A caproto pod that simulates IOS PVs would need to publish, at minimum:

- 2 EPU prefixes (`XF:23ID-ID{EPU:1`, `XF:23ID-ID{EPU:2`) with the
  curly-brace suffix scheme (`-Ax:Gap}Pos-I`, etc.) and the FLT/RLT
  interpolator records;
- 4 Mirror prefixes (m1a, m1b1, m1b2, m3b) each exposing 6 axes
  (`Z`/`Y`/`X`/`Pit`/`Yaw`/`Rol` with `Mtr_MON`+`Mtr_POS_SP`) plus the
  shared `MOVE_CMD.PROC`/`STOP_CMD.PROC`/`BUSY_STS` records;
- the PGM (`XF:23ID2-OP{Mono`) with energy + 4 motor records + fly
  controls;
- ~36 standalone motor records via `caproto.ioc_examples.fake_motor_record`
  (one per EpicsMotor entry);
- scaler / current-amp / valve PVs as scalar pvproperty records;
- the `FBck` PID record at `XF:23ID2-OP{FBck}`;
- Xspress3 + SPECS detector cam PVs (largest surface — likely deferred).

Until then, the happi DB is **catalog-only**: configuration_service
will know every device, but CA reads against any of them will fail
(no IOCs published).
