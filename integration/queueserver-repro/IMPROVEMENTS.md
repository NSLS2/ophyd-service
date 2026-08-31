# IOS simulated beamline — fixes and improvements (status ledger)

Lessons carried over from the HEX simulated-beamline campaign (now at
`hex-ob/hex-simulated-beamline`; originally `NSLS2/hxm_program`
`simulated_beamlines/HEX/`), which hit many of the same problems this repro
solves (and borrowed this branch's consistent-asyn-port fix in return).

**Status (2026-08-11):** items 1 and 2 (safety) and the first three bullets of
item 5 are **DONE** — see each section. Items 3 and 4 remain open patterns to
adopt as the demo grows; the last bullet of 5 (idempotent re-init) is open.

## 1. Local-only guard — refuse non-loopback EPICS by construction (safety)

> **DONE** — `iocs/localguard.py` + `iocs/test_localguard.py`; wired into
> `verify_xs3_sim.py`, the xs3 PGM follower, and `reproduce.sh` (which refuses
> to launch the RE worker on a non-loopback address list).

The sim IOCs and the blackhole reuse **real IOS PV names**, and the repro's
worker reaches them via `EPICS_CA_ADDR_LIST`. Today that address list is set
correctly by `reproduce.sh` and the individual scripts — but nothing *refuses
to run* if it is wrong. On any machine that can route to the IOS subnet
(deployment work targets `xf23id2-ios-qs1` — an IOS host), a stray or
inherited address list would let sim-side writes reach real IOCs.

Fix: a small guard module imported *before* `epics`/`caproto` clients start —
it parses `EPICS_CA_ADDR_LIST`/`EPICS_PVA_ADDR_LIST`, forces
`*_AUTO_ADDR_LIST=NO`, and raises unless every address is loopback. Wire it
into every entry point that talks CA (IOC launch wrappers, `verify_xs3_sim.py`,
test scripts) and into `reproduce.sh` before launching the RE worker.

Reference: `simulated_beamlines/HEX/iocs/panda/localguard.py` +
`tests/localguard_test.py` (five refusal/pass cases, including the real entry
points). Port is nearly verbatim.

## 2. Audit + mark all simulated data paths

> **DONE** (audit + sentinel + sim root) — every `up` stamps the sentinel
> identity into `RE.md` (`seed_sim_md`: proposal `000000` / `pass-000000` /
> `SIMULATED`), the `/nsls2` mimic tree and the xs3 HDF path
> (`XS3_HDF_FILE_PATH`) live under the disposable `SIM_DATA_ROOT` with a
> `_SIMULATED_DATA_README` marker, and `nuke` reaps it. Audit finding kept for
> the record: no sim process writes real files; the hazards were the
> real-looking catalog paths and unmarked RE.md identity, both countered.
> Still open from the HEX pattern: a storage-budget warning + prune script
> (irrelevant while nothing writes frames; revisit if real file-writing lands).

The sim Xspress3 advertises paths under the sim root (safe). But the IOS **profile
collection's plans** may build output paths from proposal/cycle metadata the
way production does; anything that produces a real-looking
`/nsls2/data/...`/proposal-numbered path from a sim run risks being mistaken
for (or landing in) real proposal storage when run on a facility host.

Fix: (a) audit every write path a full plan run produces (HDF plugins, export
callbacks, Olog attachments); (b) keep everything under one disposable sim
root; (c) give the sim run an **unmistakably fake identity** — a sentinel
data session / proposal id reserved for simulation, never a real customer's —
and mimic the `/nsls2` tree only *under the sim root*, bind-mounting it where
containers expect `/nsls2`.

Reference: HEX `scripts/sync_sim_experiment.sh` (sentinel `pass-000000`,
proposal `type: SIMULATED`, `_SIMULATED_DATA_README` marker,
`/tmp/hex-sim-data/nsls2/...` mimic) and the storage-budget/prune pattern
(`scripts/prune_sim_data.sh`).

## 3. Typed-demand probe + personality overlay (for the ophyd-async future)

The IOS profile is classic ophyd today, but this service's direction is
ophyd-async, whose typed devices verify the PV surface **at connect time**
(StrictEnum choices must match as a *set*; `SubsetEnum`/`SupersetEnum` have
their own rules — worth knowing before chasing false mismatches). When IOS
devices migrate, two HEX techniques transfer directly:

- **Probe**: mock-connect the typed device, walk its signals for the full PV
  demand (name, datatype, enum class), then diff against the live sim IOC.
  On HEX this reduced a feared "rewrite the sim" job to exactly two PVs.
- **Personality overlay**: when a *real* IOC (e.g. an ADSimDetector container)
  provides frames but lacks device-specific PVs, serve **only the missing
  PVs** from a caproto server — no CA conflict, because the real IOC never
  answers searches for names it doesn't have. Enum-choice gaps on existing
  records can be fixed at runtime by rewriting mbbo state strings
  (`record.ONST`, `.TWST`, ...).

Reference: HEX `iocs/sim_devices/_ophyd_async_sim.py` (introspection),
`iocs/sim_devices/kinetix_sim.py::build_kinetix_overlay_pvdb` (overlay),
`iocs/kinetix/init_kinetix.py` (mbbo state extension),
`iocs/panda/tests/kinetix_typed_connect_test.py` (the proof).

## 4. Cross-IOC software wiring: prefer cumulative counters over edge signals

Where one sim IOC must follow another (the feedback IOC pattern, or a future
"detector follows a trigger" link), bridge on a **cumulative tally** rather
than the pulse/edge itself: a missed monitor update then heals itself on the
next update (catch up by the delta), and a counter reset just rebaselines.
HEX's TTL trigger bridge (`iocs/panda/ttl_trigger_bridge.py`) is the worked
example, including the bounded catch-up so a stale bridge can't machine-gun
its target.

## 5. Small hardening items

> First three bullets **DONE**: `BLACKHOLE_ASYN_PORT` (default `BHPORT`) is in
> `blackhole_ioc.py`; `reproduce.sh smoke` runs unit + acceptance + live
> round-trip + tiled contract checks, where a check that cannot run counts as
> a failure; `README.md` is the front door. Last bullet (idempotent re-init
> script) still open — becomes relevant with real vendor-IOC containers.

- `blackhole_ioc.py`: make the asyn port name env-overridable
  (`BLACKHOLE_ASYN_PORT`, default `BHPORT`) — costs nothing, helps when two
  fabricated device trees must coexist.
- `reproduce.sh`: add a `--smoke` mode that runs the existing checks
  (`test_blackhole_types.py`, `verify_xs3_sim.py`, a blackhole round-trip)
  as one command after bring-up, so "is the stack healthy" is a single
  invocation. (HEX equivalent: the `tests/` suite listed in its PROGRESS
  pre-flight, ~90 s, all exit 0.)
- Give this directory a `README.md` front door: what the repro is, the port
  map, the safety rules, and a quickstart — separate from the running history
  in commit messages. On HEX, splitting the stable front door from the
  running log is what kept the front door from rotting.
- After any IOC container/process recreate, re-apply runtime-only settings
  from one idempotent init script (HEX: `init_kinetix.py` for
  autosave-equivalents like `ArrayCallbacks=1` — the class of settings that
  production autosave restores and fresh sims silently lack).

## Suggested order

1 (guard) and 2 (path audit) were the safety items — both done, as is 5's
smoke mode. What remains: 3 and 4 are patterns to adopt opportunistically as
the demo grows (tracked as design decisions), plus 5's idempotent re-init
bullet when vendor-IOC containers arrive.
