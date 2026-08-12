# IOS queueserver demo pod

**NSLS-II-specific development/demonstration asset.** Lives on the
`demo/ios-nsls2*` branches only — never merged to the upstream community
`main`.

This pod stands up the **real upstream `bluesky-queueserver` +
`bluesky-httpserver`** (the packages a beamline actually deploys — *not*
this repo's `queueserver_service`) running the NSLS-II **IOS profile
collection**. It answers two questions:

> Can the existing queueserver open the IOS profile collection cleanly, and
> serve its plans and devices over HTTP for a frontend to drive? And can it
> RUN those plans against a faithful simulated beamline, with the run data
> landing in a Tiled-served catalog?

`configuration_service` and `direct_control_service` are **not** part of this
pod — this phase is only about the queueserver + httpserver + the profile.

It mirrors the NSLS-II ansible `bsqs` role (pixi-installed profile `qs`
environment, `start-re-manager` for the RE Manager, `uvicorn
bluesky_httpserver.server:app` for the HTTP API), adapted to run in containers.

## Quick start

From the repo root:

```bash
./integration/pods/ios-queueserver/run_demo.sh
```

That builds the images, brings the pod up, opens the RE Manager environment
(which imports the IOS profile), and verifies the httpserver serves the
profile's plans and devices. First build is slow (~several minutes: it
`pixi install`s the whole bluesky/ophyd/nslsii stack). Subsequent runs reuse
the image.

Common flags:

```bash
./integration/pods/ios-queueserver/run_demo.sh --rebuild      # force --build
./integration/pods/ios-queueserver/run_demo.sh --skip-verify  # up + open env only
./integration/pods/ios-queueserver/run_demo.sh --tear-down    # verify then down -v
```

Tear down by hand:

```bash
docker compose -f integration/pods/ios-queueserver/docker-compose.yaml down -v
```

## Architecture

```
   frontend / curl
        │  HTTP (port 60610)
        ▼
  ┌──────────────┐   ZMQ tcp    ┌──────────────┐
  │ httpserver   │─────────────▶│ queueserver  │  start-re-manager
  │ (uvicorn)    │  60615/60625 │ (RE Manager) │  opens IOS profile
  └──────────────┘              └──────┬───────┘
                                       │
             ┌─────────────┬───────────┼───────────────┐
             ▼             ▼           ▼               ▼
        ┌─────────┐  ┌──────────┐ ┌─────────┐   Channel Access
        │ redis   │  │ redis    │ │ mongo   │        │
        │ :6379   │  │ :6380 TLS│ │ :27017  │        ▼
        │ (queue  │  │ (RE.md,  │ │ (db 'ios'│  ┌──────────────┐
        │  store) │  │  profile)│ │  tiled)  │  │ blackhole IOC│
        └─────────┘  └──────────┘ └─────────┘   │ (all PVs)    │
                                                └──────────────┘
```

## Services

| Service | Image | Role |
|---|---|---|
| `redis` | `./redis` (redis:7 + TLS) | 6379 plain = RE Manager queue store; 6380 TLS = the IOS profile's `RE.md` store (`nslsii.configure_base(redis_ssl=True)`) |
| `mongo` | `mongo:6` | Backend for the databroker `ios` tiled profile. In databroker 2.0, `Broker.named('ios')` resolves via `tiled.from_profile('ios')`, which needs a live mongo |
| `kafka` | `apache/kafka:3.9.0` | Single-node KRaft broker — the RunEngine publishes documents during a plan; without it plans block |
| `olog` | `./ioc` image | Mock Olog (stdlib) — the profile's logbook callback POSTs a logbook entry on every run start |
| `iocs` | `./ioc` (context `integration/`) | The simulated IOS beamline: the SHARED suite from `integration/queueserver-repro/iocs` — 7 realistic caproto IOCs (pgm, curramp, epu, vortex, scaler, feedback, xspress3 with modeled absorption edges) on CA ports 5064..5076 plus the blackhole catch-all (with the HDF/AD type rules) on 5078, exclusion list harvested at start |
| `seed-identity` | `Dockerfile.queueserver` | One-shot: stamps the SIMULATED sentinel identity (proposal `000000` / `pass-000000`) into `RE.md` so every run start document is unmistakably fake |
| `queueserver` | `Dockerfile.queueserver` | `start-re-manager` against the profile's `qs` pixi env; imports `startup/*.py` on environment open |
| `httpserver` | `Dockerfile.queueserver` | `bluesky-httpserver` — the HTTP API the frontend calls (port **60610**) |
| `tiled` | `Dockerfile.queueserver` | `tiled serve config` over the mongo catalog (port **8000**, anonymous, CORS for the frontend dev origin) — what the RunEngine wrote is what browsers read |

## What the frontend talks to

The httpserver exposes the standard bluesky-queueserver HTTP API on
`http://localhost:60610`. Anonymous clients may read `/api/status` and console
output only; reading the queue, allowed plans, and allowed devices — and every
write operation — requires the single-user API key (`Authorization: ApiKey
<key>`; default `iosdemosecretkey0123456789`, set in `docker-compose.yaml`). In
practice the frontend sends the key on every request.

A minimalist frontend setup + endpoint reference for building the React UI is
in `frontend-tutorial.html` (open it in a browser). The httpserver also serves
live interactive API docs at `http://localhost:60610/docs` and the spec at
`/openapi.json`.

```bash
KEY=iosdemosecretkey0123456789
AUTH=(-H "Authorization: ApiKey $KEY")

# Open the environment (imports the IOS profile). POST.
curl "${AUTH[@]}" -X POST http://localhost:60610/api/environment/open

# Manager + worker status. GET.
curl "${AUTH[@]}" http://localhost:60610/api/status | jq

# The profile's plans and devices. GET.
curl "${AUTH[@]}" http://localhost:60610/api/plans/allowed   | jq '.plans_allowed   | keys | length'
curl "${AUTH[@]}" http://localhost:60610/api/devices/allowed | jq '.devices_allowed | keys | length'

# Queue a plan and run it. POST.
curl "${AUTH[@]}" -X POST http://localhost:60610/api/queue/item/add \
  -H 'Content-Type: application/json' \
  -d '{"item":{"name":"count","args":[["au_mesh"]],"item_type":"plan"}}'
curl "${AUTH[@]}" -X POST http://localhost:60610/api/queue/start
```

A healthy run reports ~**145 allowed plans** and ~**100 allowed devices** from
the IOS profile (e.g. plans `XAS_edge_scan`, `PEY_XAS_scan`, `E_ramp`; devices
`au_mesh`, `pgm`, `epu1`, `sclr`).

## How the profile's infrastructure is satisfied

The IOS `startup/00-startup.py` calls
`nslsii.configure_base(broker_name='ios', publish_documents_with_kafka=True,
redis_url=..., redis_port=6380, redis_ssl=True)` plus olog and amostra. The pod
satisfies each dependency without touching the profile source:

- **Redis (TLS)** — the `redis` service serves a TLS port (6380) with a
  self-signed cert for hostname `redis`. The queueserver points the profile at
  it via `REDIS_HOST`/`REDIS_PORT`/`REDIS_SECRET_FILE` (honored by
  `nslsii.open_redis_client`) and trusts the cert via `SSL_CERT_FILE`.
- **databroker `ios`** — a tiled profile named `ios`
  (`config/home/.config/tiled/profiles/ios.yml`) backed by the empty `mongo`.
- **Kafka** — `config/kafka.yml` points at the pod's `kafka` broker, so
  document publishing (and therefore running plans) completes.
- **olog / amostra** — `~/.pyOlog.conf` points at the pod's mock Olog, so the
  logbook callback on every run start succeeds.
- **EPICS** — the `iocs` service serves the realistic per-device IOCs plus the
  blackhole catch-all (deferring on harvested PV names), so all ~100 devices
  connect AND the ones plans touch behave like hardware (slew, counting,
  spectra, an energy-coupled fluorescence edge).
- **Permissions** — `config/user_group_permissions.yaml` (the standard
  permissive set) lets the RE Manager build the allowed plan/device lists the
  frontend reads.

## Relationship to the ansible `bsqs` role

This pod is the containerized equivalent of deploying the `bsqs` role to a
queueserver VM: same `pixi run -e qs start-re-manager` / `uvicorn
bluesky_httpserver.server:app`, same profile-collection layout, same
config-file shape (`config/bluesky-queueserver-config.yml`,
`config/bluesky-httpserver-config.yml`). Differences are container-driven: ZMQ
sockets bind on TCP instead of IPC, and Redis TLS + mongo are provided as pod
services instead of beamline infrastructure.

## Running a scan end to end

With the pod up and the environment open:

```bash
KEY=iosdemosecretkey0123456789
curl -H "Authorization: ApiKey $KEY" -H 'Content-Type: application/json' \
  -X POST http://localhost:60610/api/queue/item/add \
  -d '{"item":{"item_type":"plan","name":"XAS_scan","args":[635,670,0.1,6.5],"kwargs":{"inc_vortex":true}}}'
curl -H "Authorization: ApiKey $KEY" -X POST http://localhost:60610/api/queue/start
```

The run's documents land in mongo and serve from Tiled:
`http://localhost:8000/api/v1/search/` lists runs; PFY traces the simulated
Mn L-edge. Every run carries the SIMULATED sentinel identity.

## Configuration reference

```
integration/pods/ios-queueserver/
├── docker-compose.yaml            # the pod
├── run_demo.sh                    # build + up + open env + verify
├── Dockerfile.queueserver         # pixi + IOS profile `qs` env (queueserver & httpserver)
├── redis/                         # redis:7 + native TLS (self-signed cert at start)
├── ioc/                           # sim-beamline image: shared queueserver-repro/iocs suite
│   ├── Dockerfile                 #   (build context = integration/, no stale copies)
│   └── run_sim_beamline.sh        #   start 7 IOCs, harvest PVs, start blackhole
└── config/
    ├── bluesky-queueserver-config.yml   # RE Manager config (mirrors bsqs role)
    ├── bluesky-httpserver-config.yml    # httpserver config (zmq addrs + auth)
    ├── kafka.yml                        # nslsii kafka config -> pod broker kafka:9092
    ├── tiled-server-config.yml          # tiled read-view over mongo (+ CORS origins)
    ├── seed_sim_md.py                   # sentinel identity seeder (one-shot service)
    ├── user_group_permissions.yaml      # allowed plans/devices per group
    └── home/                            # HOME for the profile
        ├── .pyOlog.conf                 #   -> mock olog service
        └── .config/tiled/profiles/ios.yml
```

Change the profile branch by rebuilding with a build arg:

```bash
docker compose -f integration/pods/ios-queueserver/docker-compose.yaml build \
  --build-arg PROFILE_BRANCH=pixi_2026C2
```

## Troubleshooting

- **`up` hangs on queueserver becoming healthy** — the manager is imported but
  the environment isn't open yet; that's expected. `run_demo.sh` opens it.
  Watch progress with `docker compose ... logs -f queueserver`.
- **Environment open times out** — check `docker compose ... logs queueserver`
  for the failing `startup/*.py`. A stuck import is usually a missing
  dependency the blackhole IOC can't fake.
- **httpserver 401 on writes** — send the API key:
  `-H "Authorization: ApiKey iosdemosecretkey0123456789"`.
- **`redis` TLS errors in the queueserver log** — the shared `redis-certs`
  volume may be stale from an earlier cert. `docker compose ... down -v` to
  reset it.
