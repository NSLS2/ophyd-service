# Ancestry and functional parity

`queueserver_service` is a hard fork of two upstream packages, merged into one
package and restructured for maintainability. It is functionally equivalent to
its ancestors: the merge and restructure changed the shape of the code, not its
behavior. The value inherited from upstream — years of production use at
beamlines — is preserved by keeping the full functional surface and the full
upstream test suites.

## Ancestors and baselines

| Upstream package | Baseline | Lives on as |
|---|---|---|
| [bluesky-queueserver](https://github.com/bluesky/bluesky-queueserver) | v0.0.24 + the three v0.0.25 fixes (ported 2026-08) | `queueserver_service/manager/` |
| [bluesky-httpserver](https://github.com/bluesky/bluesky-httpserver) | v0.0.14 + PR #81 (tiled-v0.2.12 auth stack, ported 2026-08) | `queueserver_service/http/` |

The shared 0MQ/JSON-RPC layer (`comms`, `json_rpc`, `logging_setup`) was lifted
into `queueserver_service/common/`. Both distributions are still published under
their upstream names (`bluesky-queueserver` 1.0.0, plus the `bluesky-httpserver`
shim) so `bluesky-queueserver-api` and legacy imports resolve here — see the
provenance comments in `pyproject.toml` and the two shim `__init__.py` files.

## What is preserved (audited 2026-08-07)

A three-way surface inventory (both ancestors vs this tree) found **zero dropped
features**:

- All 50 upstream 0MQ methods, name-for-name, in the manager dispatch table.
- All upstream REST endpoints and the three WebSockets. Upstream's monolithic
  `core_api` module was domain-split into `http/routers/*`, handler-for-handler.
- All 9 CLI entry points (`qserver`, `start-re-manager`,
  `start-bluesky-httpserver`, …) with unchanged names.
- The full auth stack (all 8 authenticator classes, device-code flow, API keys,
  sessions, scopes/roles, access-policy seams), Redis persistence keys, queue
  modes, permissions YAML schema, plan validation, IPython-kernel worker mode.
- The upstream test suites themselves: 38 of the 63 test modules are carried
  from the ancestors (~2900 tests after parametrization), plus a Side-C CI job
  that drives the real PyPI `bluesky-queueserver-api` client against this tree.

## What the restructure changed (shape, not behavior)

- One package, one test tree, one CI pipeline instead of two repos.
- Composition and dependency injection over inheritance where seams were
  needed: `QueueStore` protocol (Redis or SQL queue storage), authenticator
  ABCs in `http/protocols.py`, `ConfigServiceHost` protocol,
  `RunEngineManager.register_command`, the `rm_client` injection point in
  `build_app`.
- Unified-process mode: the HTTP server can run inside the manager process,
  replacing the 0MQ client hop with an in-process loopback
  (`manager/http_server.py`).

## Fork additions (not inherited, not battle-tested upstream)

config-service integration (`config_service_diff`/`config_service_sync`, device
diff/sync), git-backed profile-collection pull/reload endpoints,
`SqlQueueStore`, `GET /api/queue/item/{uid}`, unified-process mode. Each has
dedicated tests in-tree; none has upstream field mileage.

## Deliberate divergences from the ancestors

- `GET /api/stream_console_output` streams SSE (`text/event-stream`) instead of
  upstream's chunked `text/plain`.
- `/api/about` is not served (the model exists; see `http/schemas.py`).
- Legacy import paths `bluesky_queueserver.manager.{comms,json_rpc,logging_setup}`
  are intentionally not aliased.
- `GET /api/plans/existing` requires the `read:resources` scope; upstream
  leaves it unauthenticated (an asymmetry vs `devices/existing`).
