# Simulated IOS IOCs + running the E_ramp plan

This branch (`simple-queueserver-ios-iocs`) builds on the generic
`queueserver-repro` setup by adding the simulated IOS EPICS IOCs from the
`demo/ios-nsls2` work and everything else needed to actually **run plans**
against the IOS profile collection — including the beamline's `E_ramp` plan.

`reproduce.sh up` now also:

- runs the eight purpose-built IOS caproto IOCs (`iocs/ioc_ios_*.py`): `pgm`,
  `curramp`, `epu`, `vortex`, `scaler`, `feedback`, `xspress3` — each a
  separate Channel Access server on its own port (`5064`, `5066`, …);
- runs a catch-all **blackhole** IOC (`iocs/blackhole_ioc.py`) for every other
  PV the profile's ~100 devices force-connect at startup;
- runs a **kafka** broker (RunEngine document publishing) and a minimal
  **mock Olog** server (`iocs/mock_olog.py`, the profile's logbook callback).

The RE worker reaches the IOCs through an explicit `EPICS_CA_ADDR_LIST` with
`EPICS_CA_AUTO_ADDR_LIST=NO` — the analog of the queueserver VM's dedicated,
broadcast-disabled EPICS NIC (the VM is dual-homed: a Data Services NIC for
redis/tiled/mongo/kafka/httpserver and an EPICS-only NIC to the IOC hosts).

## Realistic IOCs + catch-all, without a Channel Access race

The six realistic IOCs only cover their own device families; the profile
force-connects far more PVs than that. So a blackhole answers everything else.
To avoid two servers claiming the same PV (a non-deterministic CA race), each
realistic IOC is started with `--list-pvs`, its exact PV names are harvested,
and the blackhole is told to **defer on exactly those PVs** (and only those).
Result: realistic values where a real IOC exists (e.g. the scaler's `.TP`, the
mono energy), spoofed zeros everywhere else, and the whole profile opens fast.

## The Xspress3 sim (`ioc_ios_xspress3.py`): XAS_scan with real PFY/TFY

The profile's `xs3` fluorescence detector (nslsii `build_xspress3_class`,
1 channel, MCArois 1-4, HDF5 plugin) is what `XAS_scan` reads for PFY/TFY.
The sim serves:

- the **HDF5 file-plugin records as properly typed enums/strings** so
  ophyd's FileStore staging (`auto_save='Yes'`, `file_write_mode='Stream'`,
  `compression='zlib'`, ...) succeeds — the raw blackhole fabricated these
  as floats, which crashed staging with `int(b'Yes', 0)`;
- **trigger dynamics**: `det1:Acquire <- 1` acquires for `AcquireTime`, then
  drops back to 0 (nslsii's `Xspress3Trigger` completes on that edge);
- **energy-coupled ROI counts**: the sim polls the PGM sim's
  `}}Enrgy-I` (address passed via `XS3_PGM_ADDR`; the PGM must stay first
  in `IOS_IOCS`) and evaluates a synthetic absorption model
  (edge step + white line + post-edge decay for Ti_L/O_K/Mn_L/Fe_L/Ni_L/Cu_L),
  so an `E_ramp` across an edge traces real-looking XAS structure.
  ROI names are served as `PFY`/`TFY`/`ELASTIC`/`BKG`.

`iocs/verify_xs3_sim.py` is the acceptance check: it spawns the xs3 + PGM
sims + blackhole, instantiates the profile's exact Xspress3 class, and
asserts stage -> trigger/read below the Mn L3 edge -> slew onto the white
line -> trigger/read shows the absorption jump.

### Simulator abstraction levels (N3XTware FDR, Deliverable 4 alignment)

The FDR's Device Simulators deliverable names four abstraction levels for
simulators; this demo deliberately mixes two of them per the same
vocabulary, selected per device by one configuration source (the harvested
exclusion list):

| Level (FDR D4) | Here |
|---|---|
| stand-in | the blackhole catch-all (name-inferred channel types) |
| controls-level | the eight `ioc_ios_*.py` caproto IOCs (typed records, device dynamics) |

Hybrid simulated/real operation (SC-D4-3) maps onto the same exclusion
mechanism: a real IOC's PVs would be excluded from the blackhole exactly
like a realistic sim's are today.

## The motor sim (`ioc_ios_motor.py` + `motor_sim.py`): moves that complete

Every `EpicsMotor` in the happi seed used to resolve at the blackhole, which
fabricates `.DMOV` as a float 0 — so any `mv(motor, pos)` in a plan waited
forever. `ioc_ios_motor.py` serves the sample bar (`ioxas_x`, 0–300 mm; the
operator screen's SAMPLE 1..6 presets are 252..290 mm) and the axes the edge
plans move (`diag3_y`, `au_mesh`, `vortex_x`) as FULL EPICS motor records:
caproto's shipped `FakeMotor`, patched (`motor_sim.py`, ported from the HEX
simulated beamline) so that CA put-completion is held until the move finishes,
a zero-distance move still cycles `.DMOV` 1→0→1 (ophyd's `MoveStatus` needs
it), `.STOP` keeps position, and `.EGU`/`.VMAX`/`.DHLM`/`.DLLM` are set.
A record IOC lists only the record name under `--list-pvs`, so the blackhole
treats a listed record as owning every `.FIELD` of it. `iocs/verify_motor_sim.py`
is the acceptance check (ophyd `EpicsMotor.set()` completes, readback ramps,
zero move completes, stop works, blackhole silent on motor fields); it runs in
`reproduce.sh smoke`. Adding another motor is one line in `IOS_MOTORS`.

## What it takes to RUN a plan (beyond opening the profile)

Opening the profile needs redis (×2), mongo, a tiled `ios` profile, a kafka
config, and `~/.pyOlog.conf`. **Running** a plan needs three more things, each
discovered by running `count` / `E_ramp` and watching where it stalled:

| Requirement | Why | Provided by |
|-------------|-----|-------------|
| Kafka **broker** on `:9092` | the RunEngine publishes documents to Kafka; the publisher blocks on a dead broker | `WITH_KAFKA=1` (KRaft broker container) |
| Responsive **Olog** server | the profile subscribes an Olog logbook callback that POSTs on every run start; no server → the run errors/blocks | `WITH_OLOG=1` (`iocs/mock_olog.py`) |
| Scaler `.CONT` record | bluesky stages the scaler by setting count-mode to one-shot; the set must confirm | added to `iocs/ioc_ios_scaler.py` |

## E_ramp-specific fidelity

`E_ramp` (in the profile's `98-ramp.py`) is a fly scan: it sets the mono fly
start/stop/velocity, triggers `pgm.fly.fly_start`, then `ramp_plan` reads the
detectors while the energy ramps, finishing when `pgm.fly.scan_status`
transitions to **`Ready`**. The stock `ioc_ios_pgm.py` only had `Idle`/`Scanning`
states, so `ramp_plan` never saw the done event. `scan_status` now includes a
`Ready` state and rests/returns there, so `E_ramp` completes.

## Run it

```bash
cd integration/queueserver-repro
./reproduce.sh up            # profile + infra + IOCs + kafka + mock Olog + services
```

Then drive a plan through the HTTP API (API key is printed by `up`, also in
`$QS_REPRO_HOME/config/secrets.env`):

```bash
KEY=$(sed -n 's/^HTTP_API_KEY=//p' "$HOME/qs-repro/config/secrets.env")
BASE=http://localhost:60610

# a simple count on the (realistic) scaler
curl -s -X POST $BASE/api/queue/item/execute \
  -H "Authorization: ApiKey $KEY" -H "Content-Type: application/json" \
  -d '{"item":{"name":"count","args":[["sclr"]],"kwargs":{"num":3},"item_type":"plan"}}'

# the beamline E_ramp fly scan: E_ramp(dets, start_eV, stop_eV, velocity_eV_s)
curl -s -X POST $BASE/api/queue/item/execute \
  -H "Authorization: ApiKey $KEY" -H "Content-Type: application/json" \
  -d '{"item":{"name":"E_ramp","args":[["sclr"],850,852,0.5],"item_type":"plan"}}'
```

Watch progress with `./reproduce.sh status` and `./reproduce.sh logs`.

Verified end to end: `E_ramp([sclr], 850, 852, 0.5)` completes with
`exit_status=success`, ~130 event documents captured, the mono energy readback
ramps 850 → 852 eV, and `Sts:Scan-Sts` returns to `Ready`.

## Toggles (environment variables)

`WITH_IOS_IOCS`, `WITH_REALISTIC_IOCS`, `WITH_BLACKHOLE`, `WITH_KAFKA`,
`WITH_OLOG`, `IOC_BASE_PORT`, `KAFKA_PORT`, `OLOG_PORT` — see the header of
`reproduce.sh` for the full list and defaults.

## Note on the IOC changes

`iocs/ioc_ios_pgm.py` (added a `Ready` scan-status state) and
`iocs/ioc_ios_scaler.py` (added the `.CONT` count-mode record) are lightly
adapted from the `demo/ios-nsls2` originals so the profile's plans stage and
complete under the queueserver. `iocs/blackhole_ioc.py` is ported from the
phase-1 `demo/ios-nsls2-queueserver` pod with exact-PV exclusion added.
