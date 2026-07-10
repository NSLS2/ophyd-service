# IOS queueserver demo pod (phase 1)

**NSLS-II-specific development/demonstration asset.** Lives on the
`demo/ios-nsls2*` branches only — never merged to the upstream community
`main`.

This pod stands up the **real upstream `bluesky-queueserver` +
`bluesky-httpserver`** (the packages a beamline actually deploys — *not*
this repo's `queueserver_service`) running the NSLS-II **IOS profile
collection**. It answers one question:

> Can the existing queueserver open the IOS profile collection cleanly, and
> serve its plans and devices over HTTP for a frontend to drive?

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
| `blackhole` | `./ioc` | Catch-all caproto IOC — resolves *every* IOS PV so all ~100 devices connect at profile import. Phase-1 stand-in for real hardware |
| `queueserver` | `Dockerfile.queueserver` | `start-re-manager` against the profile's `qs` pixi env; imports `startup/*.py` on environment open |
| `httpserver` | `Dockerfile.queueserver` | `bluesky-httpserver` — the HTTP API the frontend calls (port **60610**) |

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
- **Kafka** — `config/kafka.yml` is read, but there is no broker in the pod.
  nslsii catches the connection failure and continues (publishing is a no-op);
  environment open still succeeds after a short timeout.
- **olog / amostra** — `~/.pyOlog.conf` is provided; both clients construct
  lazily and need no server to open the profile.
- **EPICS** — the `blackhole` IOC answers every PV, so all devices connect.
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

## Phase 2

Phase 1 uses the catch-all `blackhole` IOC so the profile opens with every PV
resolved. Phase 2 swaps in the realistic per-device IOS IOCs already on this
branch (`integration/ioc/ioc_ios_*.py`: pgm, curramp, epu, vortex, scaler,
feedback) for a more faithful hardware simulation.

## Configuration reference

```
integration/pods/ios-queueserver/
├── docker-compose.yaml            # the pod
├── run_demo.sh                    # build + up + open env + verify
├── Dockerfile.queueserver         # pixi + IOS profile `qs` env (queueserver & httpserver)
├── redis/                         # redis:7 + native TLS (self-signed cert at start)
├── ioc/                           # catch-all "black hole" caproto IOC
└── config/
    ├── bluesky-queueserver-config.yml   # RE Manager config (mirrors bsqs role)
    ├── bluesky-httpserver-config.yml    # httpserver config (zmq addrs + auth)
    ├── kafka.yml                        # nslsii kafka config (no broker)
    ├── user_group_permissions.yaml      # allowed plans/devices per group
    └── home/                            # HOME for the profile
        ├── .pyOlog.conf
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
