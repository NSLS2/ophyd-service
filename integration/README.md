# ophyd-service integration environments

Self-contained docker-compose test/demo environments for exercising
`configuration_service`, `direct_control_service`, and the in-tree
`queueserver_service` against simulated IOCs. Reproducible by anyone with
docker — no facility accounts, no VPN, no hand-deployed systemd units.

These pods are the project's primary test target.

## Layout

```
integration/
├── ioc/                       # caproto IOC image (mini_beamline by default;
│                              # ioc_adsim.py adds a simulated AreaDetector camera)
├── happi/
│   ├── happi_db.json          # canonical device DB (mini_beamline seed)
│   └── runtime_seed.json      # devices the exercisers register at runtime (camera, …)
├── localdevs/localdevs.py     # vanilla-ophyd compound classes (Spot, Det, RandomWalk, Thermo, …)
├── profile_collections/
│   └── test_collection/       # minimal bluesky profile collection (startup scripts
│                              # + user_group_permissions.yaml) for the queueserver pods
├── pods/
│   ├── minimal/               # 1 IOC + postgres + 2 backends
│   ├── full/                  # 7 IOCs + postgres + 2 backends (+ opt-in frontend)
│   ├── dev/                   # hot-reload backends + frontend dev server
│   ├── standalone/            # direct_control only — file-registry mode, no config service
│   ├── with-queueserver/      # + queueserver (unified mode) + redis, happi-seeded registry
│   └── profile-seeded/        # + queueserver + redis; EMPTY registry seeded from the
│                              # profile collection; per-plan device locking enforced
└── exercise/
    ├── _exerciser_lib.sh              # shared bash helpers (step/pass/fail/expect_*)
    ├── configuration_service.sh       # bash + curl + jq
    ├── direct_control.sh              # bash + curl + jq (HTTP only)
    ├── direct_control_standalone.sh   # file-registry standalone-mode walk
    ├── direct_control_ws.py           # python + websockets (pv-socket + device-socket)
    ├── queueserver_api_compat.py      # PyPI bluesky-queueserver-api client, 0MQ + HTTP
    └── registry_roundtrip.sh          # full lifecycle: seed → CRUD → export → re-import
```

## Compose surfaces

| Surface | Use case |
|---|---|
| `ophyd-service/docker-compose.yml` (repo root) | **Inner loop.** 1 IOC + 2 backends, happi-seeded. Fast iteration on a single backend. |
| `pods/minimal/` | **Smoke test.** 1 IOC + 2 backends, no hot-reload. Quick "does the wiring still work?" |
| `pods/full/` | **Integration / demo.** 7 IOCs (incl. the simulated camera) + 2 backends. More device shapes for end-to-end testing. |
| `pods/dev/` | **Joint backend + frontend dev.** 2 IOCs + 2 backends in hot-reload + frontend dev server. |
| `pods/standalone/` | **Standalone direct_control.** File-registry mode: no configuration_service, no database. |
| `pods/with-queueserver/` | **Queueserver integration.** Happi-seeded registry consumed by the unified-mode queueserver. |
| `pods/profile-seeded/` | **Profile-collection bootstrap + locking.** Registry starts empty, queueserver seeds it; per-plan device locks enforced through direct_control. |

Most surfaces mount the same `integration/happi/happi_db.json` as the device
registry source; the exceptions are `standalone/` (its own `registry.json`)
and `profile-seeded/` (starts empty by design). Devices that have no live IOC
in the chosen surface are still listed (the registry is a *catalog*); reads
against them will fail at the CA layer.

## Pods

### `pods/minimal/`

Smallest shape that exercises the happi-seeded registry end-to-end. Four
services: `ioc` (caproto `mini_beamline`), `postgres`, `configuration_service`,
`direct_control_service`. Coordination check off, CA search limited to the pod
network.

```sh
cd integration/pods/minimal
docker compose up --build
```

### `pods/full/`

Seven IOCs + postgres + the two backends. Adds `random_walk` ×3 (different
prefixes), `thermo_sim`, `fake_motor_record`, and `ioc_adsim` (a simulated
AreaDetector) to the mini_beamline base. Lets you exercise the registry against
a more realistic device mix and run the WebSocket exerciser against a live,
ticking PV — including a live camera image. A frontend container is defined
behind an opt-in profile (`docker compose --profile frontend up --build`) so it
cannot break backend/integration CI.

```sh
cd integration/pods/full
docker compose up --build
```

Most IOCs build from the same `integration/ioc/Dockerfile` and pick a caproto
module via per-service `command:`; `ioc_adsim` runs the custom
`integration/ioc/ioc_adsim.py` (copied into the image). Health is gated on
every IOC reaching `service_healthy`. (A real EPICS `areaDetector`
ADSimDetector IOC would be a drop-in replacement — the PV names match.)

**Stream the simulated camera.** `ioc_adsim` serves `13SIM1:cam1:*` + a live
`13SIM1:image1:ArrayData` (a Mono/UInt8 frame with an orbiting blob, ~5 Hz) —
the default PVs the direct-control `camera-socket` / `tiff-socket` fall back
to. The image-array PV must be in the registry first (the sockets gate on it),
so register the detector once, then connect:

```sh
# 1. register the camera device (the `cam` body from runtime_seed.json)
curl -s -X POST http://localhost:8004/api/v1/devices \
  -H 'content-type: application/json' \
  -d "$(python3 -c "import json;print(json.dumps(json.load(open('../../happi/runtime_seed.json'))['compound_devices']['cam']))")"
# 2. open the camera socket (subscribe with {} uses the 13SIM1 defaults):
#    ws://localhost:8003/api/v1/camera-socket   — JSON {x,y} then binary JPEG frames
#    ws://localhost:8003/api/v1/tiff-socket     — send {"prefix":"13SIM1"}
```

### `pods/dev/`

**The recommended environment for joint backend + frontend development.** Runs
two IOCs (caproto `mini_beamline` + `fake_motor_record` for real motor records
with `.RBV`/`.VAL`/`.VELO`/etc.), postgres, both backends in **uvicorn
`--reload` hot-reload mode** with bind-mounted source, and a **`node:20`
frontend container** running `npm run dev` against bind-mounted `frontend/`.

```sh
cd integration/pods/dev
docker compose up --build
```

What's published to the host:

| Port | Service | Notes |
|---|---|---|
| `5173` | frontend | vite dev server, HMR over WS |
| `8003` | direct_control_service | uvicorn with `--reload` |
| `8004` | configuration_service | uvicorn with `--reload`, happi-loaded |

**Backend hot-reload:** edit anything under `backend/configuration_service/src/`
or `backend/direct_control_service/src/` on the host — uvicorn detects within
~1s and restarts the worker. Confirmed by tailing
`docker compose logs configuration_service`.

**Frontend hot-reload:** edit anything under `frontend/src/` on the host — vite
HMR pushes the change to the browser. (`CHOKIDAR_USEPOLLING=true` is set so
file events propagate cleanly across the bind mount.)

**Frontend node_modules isolation:** the container uses an anonymous volume on
`/app/node_modules` so the host's modules don't bleed in. First `up` populates
it via `npm install` (~9s); subsequent ups reuse the volume.

**Frontend boundary respected:** this compose is provided by the backend team.
The frontend container's behavior is fully controlled by `frontend/`'s own
`package.json` + `vite.config.ts` — we don't override anything inside
`frontend/`. The frontend team can swap node version, change scripts, add
proxies, etc., without touching this compose file.

The dev pod's registry is the base happi seed plus three CRUD-friendly motor
records (`motor1`–`motor3` at `sim:mtr1`–`sim:mtr3`).

### `pods/standalone/`

Demonstrates (and CI-checks) **file-registry standalone mode**: the full
`direct_control_service` — PV control, device-level control, WebSocket
monitoring — with **no `configuration_service` and no database**. The
`registry.json` in the pod directory is the registry of record; a commented
schema walk-through lives at
`backend/direct_control_service/examples/standalone_registry.example.yaml`.

```sh
cd integration/pods/standalone
docker compose up --build
../../exercise/direct_control_standalone.sh
```

### `pods/with-queueserver/`

Adds the in-tree queueserver (unified mode: `start-re-manager` co-hosting the
FastAPI httpserver, HTTP + WS on `:60610`, 0MQ CONTROL/INFO on
`:60615`/`:60625`) plus the redis it requires, alongside
`configuration_service` and `direct_control_service`. The image is built from
`backend/queueserver_service/` — nothing is pulled from an external git ref.
`qs_config.yml` points the queueserver's config-service client at
`configuration_service:8004`; `integration/localdevs/` is mounted for the
config-service consume-mode device injection. Runs the shipped ophyd.sim
profile.

```bash
cd integration/pods/with-queueserver
docker compose up --build
./smoke.sh                                              # health + Side-B behavioral checks
curl -H "Authorization: ApiKey mad" localhost:60610/api/status
```

The 0MQ ports are published so
`exercise/queueserver_api_compat.py` can drive the manager through the real
PyPI `bluesky-queueserver-api` client over both transports (see below).

### `pods/profile-seeded/`

Sibling to `with-queueserver/`, covering the **opposite bootstrap direction**:
there the registry is seeded from `happi_db.json` and the queueserver consumes
it; here `configuration_service` starts **empty** and the queueserver
populates it from a realistic profile collection
(`integration/profile_collections/test_collection`) on environment open — the
"no happi registry to import" story. It is also the first pod that runs
direct_control with the **coordination check enabled**, so device locks written
by the queueserver (`config_service.lock_scope: plan`) are enforced end-to-end:
locked devices answer `423` while a plan is executing.

```sh
cd integration/pods/profile-seeded
docker compose up --build
./exercise.py       # registry bootstrap, source-of-truth checks, per-plan locking
```

## Shared assets

### `happi/happi_db.json`

Canonical device DB. **Single-IOC seed: only
`caproto.ioc_examples.mini_beamline`'s devices** (26 entries — `spot` /
`pinhole` / `edge` / `slit` compounds, motor scalars, beam_current, plus
leaf-PV entries for compound device sub-fields).

This intentionally mirrors how a real beamline boots: start with one known-good
IOC's profile, then **extend the registry at runtime via CRUD** as additional
IOCs / detectors come online. The other IOCs we run (random walks, thermo_sim,
fake_motor_record) are added via `POST /api/v1/devices` rather than baked into
the happi seed — `happi/runtime_seed.json` holds the request bodies the
exercisers use. See `exercise/registry_roundtrip.sh` for the canonical
extend-then-export pattern.

**Compound devices and the leaf-entry pattern (option (a)):** real beamlines
use compound device classes; the happi loader does pure JSON parsing and does
**not** enumerate a compound device's sub-PVs into `registry.pvs`.
`direct_control_service` validates at the leaf level (`mini:dot:img_sum`, not
`mini:dot`). Solution: alongside each compound entry, add explicit
`ophyd.signal.EpicsSignal` entries for the leaf PVs. See `spot` + `spot_*` for
the pattern.

**Source of truth for PV prefixes:** the running IOC's `--list-pvs` log
(`docker compose logs ioc | grep -A50 "PVs available"`). caproto modules
publish what they publish; adjust `happi_db.json` to match, not the other way
around.

### `localdevs/localdevs.py`

Minimal vanilla-ophyd shim. Defines `Det`, `Spot`, `RandomWalk`, `Eurotherm`,
`Thermo` — all the compound classes referenced by `happi_db.json`. It is
mounted read-only (with `PYTHONPATH=/localdevs`) into every compose surface:
`configuration_service`'s happi loader imports the compound classes to index
their sub-PVs at registry-load time, and the queueserver pods use it for
config-service consume-mode device injection.

Vanilla ophyd only — no `nslsii` dependency, even though `Eurotherm`
originated there. The bluesky-pods upstream extracted it specifically to drop
that dep; we keep it that way so this integration env stays community-friendly
(no NSLS-II-specific packages).

### `profile_collections/test_collection/`

A minimal but realistic bluesky profile collection: numbered startup scripts
(`00-base.py`, `10-devices.py`, `20-plans.py`) plus
`user_group_permissions.yaml`. Used as the queueserver startup dir by
`pods/profile-seeded/` to prove the registry can be bootstrapped from a
profile collection instead of a happi file.

## Endpoint exercisers (`exercise/`)

These walk every public endpoint family on each backend as a first-time user
would, exit non-zero on any assertion miss, and are CI-ready. Instead of
pre-populating test data, they *verify* the service from a fresh happi-seeded
state. The bash exercisers share helpers via `_exerciser_lib.sh`.

```sh
# pod must be up first
./integration/exercise/configuration_service.sh         # ~30 endpoint checks
./integration/exercise/direct_control.sh                # HTTP-only walk
uv run --with websockets integration/exercise/direct_control_ws.py
./integration/exercise/registry_roundtrip.sh            # full lifecycle round-trip

# pod-specific:
./integration/exercise/direct_control_standalone.sh     # against pods/standalone
uv run --with bluesky-queueserver-api \
    integration/exercise/queueserver_api_compat.py      # against pods/with-queueserver
```

Override targets via env vars: `CONFIG_URL`, `DIRECT_URL`, `DIRECT_WS_URL`.
Override the WS exerciser's PV with `PV_NAME` (defaults to `mini:current`,
which ticks on every pod).

**`queueserver_api_compat.py` guards the frozen wire contract.** The wire
surfaces consumed by the PyPI `bluesky-queueserver-api` client are a frozen
public contract (see `backend/queueserver_service/README.md`); this script
drives the running with-queueserver pod through the real client package over
both transports — 0MQ (CONTROL + INFO/PUB) and HTTP — so contract drift fails
CI.

**`registry_roundtrip.sh` is the most complete real-beamline simulation.** It
validates the full lifecycle:

1. **Snapshot** the happi-seeded initial state (mini_beamline only).
2. **CRUD-extend**: register devices for every other IOC (motor records,
   random walks, thermo) via `POST /api/v1/devices` — the same path a beamline
   would use as new detectors come online.
3. **Verify** the additions landed and are retrievable.
4. **Direct-control monitors a CRUD-added PV**: HTTP read + WS
   subscribe→update→unsubscribe round-trip. Closes the loop on "registry knows
   about it → CA connects → WS streams updates" for runtime-added devices.
5. **Export** via `/api/v1/registry/export`.
6. **Validate** every exported entry has the required happi shape (`_id`,
   `name`, `device_class`, `args`, `kwargs`, `type`, `active`).
7. **Re-import**: spawn a fresh `configuration_service` container against the
   exported file. Confirm device count and names match exactly. The export is
   therefore a valid happi profile that survives a full restart.
8. **Cleanup** removes the CRUD-added devices and tears down the side
   container.

The exerciser is pod-agnostic — it works against `minimal/`, `full/`, or
`dev/` (step 4 will skip cleanly if no IOC is running for any CRUD-added PV;
the rest of the test still runs). For full coverage including step 4's WS
round-trip, use the `full/` pod.

## Extension roadmap

**Data pipeline:** add `tiled`, `mongo` (databroker), `kafka`. Lets us test
the document-streaming path end-to-end.

## Why not fork bluesky-pods?

`bluesky/bluesky-pods` is the reference for this kind of pod shape and we
cannibalize it freely — but we don't track it upstream. Reasons:

- bluesky-pods doesn't include `configuration_service` or
  `direct_control_service` — they're our services, they have to live with us.
- We want to avoid inheriting NSLS-II-specific choices wholesale.
- The pod evolves in lockstep with our service code; keeping it in the same
  repo keeps the coupling visible.

Clone `https://github.com/bluesky/bluesky-pods` separately if you want the
full reference — useful especially for the data-pipeline pieces when we build
that phase.
