# Outbound compatibility veneers

Everything in this directory exists to serve **other people's code** — names the
ecosystem hardcoded against the ancestors this service merged
(`bluesky-queueserver` + `bluesky-httpserver`). Nothing in
`queueserver_service` imports from here, and a guard test
(`tests/test_no_ancestor_imports.py`) fails CI if that ever changes. The
dependency direction is one-way by decision: these packages import **from**
the service, never the reverse.

Each veneer has a written retirement condition. When the condition is met,
delete the veneer — do not extend it.

## `bluesky_queueserver/` (import namespace, ~80 lines)

**Who needs it:** the PyPI `bluesky-queueserver-api` client (installed in the
*test* environment only — the Side-C compat suite drives the real published
client against this service) imports 0MQ comms names from
`bluesky_queueserver`; and real beamline profiles import
`bluesky_queueserver.manager.annotation_decorator` / `profile_ops` /
`profile_tools` inside the RE worker.

**Why the dist is named `bluesky-queueserver`:** so the client's
`Requires-Dist` resolves to this package instead of pulling upstream (which
would clobber the `qserver` / `start-re-manager` console scripts in the same
environment).

**Retires when:** beamline profiles migrate to the real
`queueserver_service.*` imports (the IOS profile collection is the natural
first mover) *and* the published client is no longer installed alongside the
service anywhere we support. Until then this stays; it is the whole cost of
"runs unmodified beamline profiles".

**Deliberately rejected alternatives** (do not reopen without superseding the
recorded decision): renaming the service's real package to
`bluesky_queueserver` — that would squat a living upstream project's
namespace, misdescribe a two-ancestor merger, and make the ancestor name
permanent instead of removable; and deleting the aliases now — that breaks
profiles this project does not own.

## `bluesky-httpserver/` (shim distribution)

**Who needs it:** deployments that launch the server by its upstream name —
`uvicorn bluesky_httpserver.server:app`, the pattern the NSLS-II ansible
`bsqs` role uses. The distribution also claims the `bluesky-httpserver` name
so a third-party `Requires-Dist` or explicit install resolves here instead of
pulling upstream onto the same import package.

**Retires when:** deployment tooling migrates to the native entrypoint
(`queueserver_service.http.server:app` / `start-bluesky-httpserver`). The
ansible-role update is the trigger; delete the subproject in the release after
that lands.

Installed alongside the main package: `pip install -e . -e ./compat/bluesky-httpserver`
(the Dockerfile and the queueserver-tests CI job both do).
