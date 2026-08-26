# queueserver-repro — reproduce the real queueserver on any machine

`reproduce.sh` stands up the **real upstream** `bluesky-queueserver` (RE Manager)
and `bluesky-httpserver` running an NSLS-II beamline **profile collection**, on a
fresh machine, with one command. It provisions the external services the
profile's startup code expects, then launches the two services from the
profile's own `pixi` `qs` environment — exactly how the production ansible
`bsqs` role runs them.

Default target is the **IOS** profile
(`github.com/NSLS2/ios-profile-collection`); it is parameterized for any
beamline (see *Other beamlines*).

```bash
./reproduce.sh up        # clone + build env + provision deps + launch + open + verify
./reproduce.sh smoke     # health checks: unit tests + xs3 acceptance + live round-trip
./reproduce.sh status    # containers, services, environment state
./reproduce.sh logs      # tail the RE Manager + HTTP server logs
./reproduce.sh verify    # re-print plan/device counts + HTTP API/key
./reproduce.sh down       # stop services + remove containers (keeps clone + env)
./reproduce.sh nuke       # down + delete the whole work directory
```

## Safety rules (the sims wear real IOS PV names)

The simulated IOCs and the blackhole answer to the **real IOS PV names** so
the profile collection runs unmodified. Run on a host that routes to the IOS
subnet with the wrong EPICS address list, and a "sim" write would drive real
hardware. Two mechanisms make that impossible by construction, not by
convention:

1. **Local-only guard** (`iocs/localguard.py`, tested by
   `iocs/test_localguard.py`): every repro entry point that acts as a CA
   client — the RE worker launch, the xs3 sim's PGM energy follower,
   `verify_xs3_sim.py` — forces `EPICS_CA_AUTO_ADDR_LIST=NO` and refuses to
   start unless every `EPICS_CA_ADDR_LIST`/`EPICS_PVA_ADDR_LIST` entry is
   loopback. The caproto IOCs themselves bind `--interfaces 127.0.0.1`.
2. **Unmistakably fake identity + disposable data root**: every bring-up
   stamps `RE.md` with a sentinel identity (`proposal_id=000000`,
   `data_session=pass-000000`, `PI/cycle/endstation=SIMULATED`,
   `simulated_beamline=true`), which lands in **every run start document**.
   All sim-side paths live under one disposable root
   (`SIM_DATA_ROOT`, default `~/qs-repro/sim-data`, marked with
   `_SIMULATED_DATA_README`), which mimics the `/nsls2` tree the profile
   names — under the sim root only.

What a full plan run actually writes (audited against the IOS profile @
`e817f98` and nslsii's `Xspress3HDF5Plugin`):

- **No data files at all.** The sim xs3 serves the HDF plugin PVs but
  performs no file IO, and `Xspress3HDF5Plugin.stage` creates no
  directories client-side — so nothing can land in the real
  `/nsls2/data3/ios/...` even on a facility host.
- **Catalog documents** (mongo container) carry the profile's real-looking
  `/nsls2/data3/ios/legacy/xspress3_data/...` resource paths for files that
  do not exist; the sentinel identity in the same documents is what marks
  them as simulation. Containers are removed by `down`/`nuke`.
- **Caveat — profile export helpers**: the profile's manually-invoked
  `save_xas_csv`/`save_all`/... (startup/97-misc.py, 99-settings.py) write
  CSVs under `~/User_Data/<real user name>/...`. Never call them from a sim
  session on a shared host; they are not part of `XAS_scan`/`E_ramp`.

## Port map

| Port | What |
|------|------|
| 5064, 5066, … (base + 2n) | realistic IOS caproto IOCs, one CA server each (`ioc_ios_pgm` first) |
| base + 2·N(IOCs) | blackhole catch-all CA server |

The same `iocs/` directory is the single source of the simulated beamline for the
container pods too: `iocs/Dockerfile` + `iocs/run_all_iocs.sh` run this exact
port layout inside one `ios_iocs` container for `integration/pods/ios`.
| 60610 | bluesky-httpserver HTTP API |
| 8000 | tiled data API (read view over the mongo catalog; what the frontend's data browser reads) |
| 60590 | redis — RE Manager queue/history store |
| 6380 | redis (TLS) — `RE.md` metadata store |
| 27017 | mongodb — databroker/tiled catalog |
| 9092 | kafka (KRaft) — RunEngine document publishing |
| 8181 | mock Olog server |

Everything EPICS is loopback-only (enforced by `localguard`), and tiled binds
`127.0.0.1` by default (`TILED_HOST` to change). The httpserver binds `0.0.0.0`
(as production does behind its firewall) — treat 60610 as reachable from the LAN.

## Requirements

- `git`, `curl`, `openssl`
- **Docker** (or `podman`) — runs redis ×2, mongodb, and (by default) kafka
- `pixi` — auto-installed to `~/.pixi` if missing
- Internet access (clone the profile, solve the pixi env, pull container images)

## What it provisions and why

Opening a beamline profile under the queueserver requires several services that
the profile's `00-startup.py` (`nslsii.configure_base(...)`) reaches out to. The
script supplies each, mapped to how production deploys it:

| Dependency | What the profile needs it for | Script provides | Production role |
|------------|-------------------------------|-----------------|-----------------|
| Redis (TLS, :6380) | `RE.md` metadata store (`nslsii.configure_base`, `redis_ssl=True`) | `redis:7` container, TLS + password, self-signed cert | `redis6` (+ ACME cert) |
| Redis (plain, :60590) | the RE Manager's own queue/history store | `redis:7` container, no auth | `redis` role (`bluesky-queueserver-redis`) |
| MongoDB (:27017) | `databroker.Broker.named('ios')` catalog (via tiled) | `mongo:6` container | beamline mongo |
| tiled profile `ios` | resolves `Broker.named('ios')` → the mongo catalog | generated, on `TILED_PROFILES` path | beamline tiled profiles |
| tiled server (:8000) | serves the mongo catalog over HTTP for browsers/clients | `tiled serve config` from the profile's qs env, anonymous, loopback | `tiled.nsls2.bnl.gov` |
| `kafka.yml` | `nslsii` Kafka publisher config | generated, points at the local broker, `abort=false` | `bluesky_kafka_config` |
| Kafka broker (:9092) | RunEngine document publishing during a plan | single-node KRaft container (`WITH_KAFKA=1` default) | beamline kafka cluster |
| `~/.pyOlog.conf` | stops `SimpleOlogClient()` prompting for a password | rewritten every `up` (a pre-existing user file is backed up once) | `ansible-epics-tools` olog roles |
| mock Olog (:8181) | the profile's logbook callback POSTs on every run start | stdlib mock (`WITH_OLOG=1` default) | real Olog server |
| simulated IOCs | the profile force-connects ~100 devices at startup | 7 realistic caproto IOCs + blackhole catch-all (`WITH_IOS_IOCS=1` default) | real IOC hosts |

Everything above starts by default on `up`. `WITH_IOC=1` additionally runs a
generic caproto catch-all (`mini_beamline`) for profiles that need PVs the IOS
set doesn't serve.

## The services are the real thing

The RE Manager and HTTP server are launched with:

```
pixi run --manifest-path <profile>/pixi.toml -e qs start-re-manager --config ...
pixi run --manifest-path <profile>/pixi.toml -e qs uvicorn ... bluesky_httpserver.server:app
```

i.e. the upstream binaries from the profile collection's own `qs` environment —
the same commands the `bsqs` systemd units run. The RE Manager is configured by
a YAML (`config/queueserver-config.yml`) whose `startup.startup_dir` points at
the cloned profile's `startup/` directory, and it talks to the HTTP server over
0MQ IPC sockets under the work directory.

## Configuration

Override via environment variables (defaults shown):

```
ENDSTATION=ios
PROFILE_REPO=https://github.com/NSLS2/ios-profile-collection.git
PROFILE_BRANCH=main
QS_REPRO_HOME=$HOME/qs-repro        # clone, configs, sockets, logs, secrets
PROFILE_DIR=$QS_REPRO_HOME/profile_collection
HTTP_PORT=60610                     # host port for the HTTP API
TILED_PORT=8000                     # host port for the tiled data API
TILED_HOST=127.0.0.1                # tiled bind address (loopback by default)
TILED_ALLOW_ORIGINS="http://localhost:5173 http://127.0.0.1:5173"
                                    # browser origins granted CORS access to tiled
REDIS_QUEUE_PORT=60590
REDIS_TLS_PORT=6380
MONGO_PORT=27017
KAFKA_PORT=9092
OLOG_PORT=8181
REDIS_TLS_PASSWORD=<generated hex>  # persisted in $QS_REPRO_HOME/config/secrets.env
HTTP_API_KEY=<generated hex>        # httpserver single-user key (alphanumeric)
WITH_KAFKA=1                        # 0 = no kafka broker (plans that publish may block)
WITH_OLOG=1                         # 0 = no mock Olog (logbook callback will fail)
WITH_IOS_IOCS=1                     # 0 = no simulated IOCs
WITH_REALISTIC_IOCS=1               # 0 = blackhole catch-all only
WITH_BLACKHOLE=1                    # 0 = no catch-all (profile likely won't open)
IOC_BASE_PORT=5064                  # first IOC's CA port (others step by 2)
WITH_IOC=0                          # 1 = also run a generic caproto catch-all IOC
SIM_DATA_ROOT=$QS_REPRO_HOME/sim-data   # disposable root for all simulated data paths
SIM_PROPOSAL_ID=000000              # sentinel proposal stamped into RE.md
SIM_DATA_SESSION=pass-000000        # sentinel data session stamped into RE.md
```

Generated secrets persist in `$QS_REPRO_HOME/config/secrets.env`, so re-running
`up` reuses the same Redis password and API key.

## Using it

```bash
./reproduce.sh up
# ... reports: allowed plans: 145, allowed devices: 100, and the API key

KEY=$(sed -n 's/^HTTP_API_KEY=//p' "$HOME/qs-repro/config/secrets.env")
curl -s http://localhost:60610/api/status        -H "Authorization: ApiKey $KEY"
curl -s http://localhost:60610/api/plans/allowed  -H "Authorization: ApiKey $KEY" | head -c 300
```

Swagger UI: <http://localhost:60610/docs>. Point a client
(e.g. `bluesky-widgets` `queue_monitor`) at the same base URL + API key.

## Other beamlines

Any NSLS-II profile collection with a `qs` pixi environment should work:

```bash
ENDSTATION=tst \
  PROFILE_REPO=https://github.com/NSLS2/tst-profile-collection.git \
  PROFILE_BRANCH=main \
  ./reproduce.sh up
```

The tiled profile is named after `ENDSTATION`. Profiles that reach additional
services (extra Redis DBs, a real Tiled API key, live PVs) may surface new
startup errors — `./reproduce.sh logs` shows exactly where startup stopped, the
same way each IOS dependency above was discovered.

## Relation to production

This is the **developer / any-machine** path: it spoofs the beamline
infrastructure so a profile can be opened anywhere. Production deploys the same
two services natively under **systemd**, launched with `pixi` against the
profile collection's `qs` environment, via the NSLS-II ansible `bsqs` role
(with the `redis`/`redis6`, `bluesky_kafka_config`, and nginx roles providing
the surrounding services). The dependency table above maps each spoofed service
to its production role.
