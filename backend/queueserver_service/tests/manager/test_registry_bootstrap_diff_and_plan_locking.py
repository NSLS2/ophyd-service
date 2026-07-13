"""Regressions for the queueserver-side Phase-3 tail: 3.8 (bootstrap/diff
active-only blind spot) and 3.9 (per-plan locking gaps).

3.8 covered here:

- ``sync_devices_on_env_open`` with ``prefetched_info={}`` now re-probes
  ``/devices-info`` before deciding whether to bootstrap, so a registry that
  is fully disabled (empty via ``/devices/instantiation?active_only=true``
  but non-empty via ``/devices-info``) does not get its devices silently
  re-enabled by the bootstrap upsert path.
- ``ConfigServiceClient.get_instantiation_specs`` takes ``active_only`` and
  passes it through as the query parameter of the same name.
- ``compute_diff`` recognizes ``spec.active is False`` in the registry and
  routes those names into a new ``disabled`` bucket, excluding them from
  ``added`` / ``removed`` / ``modified`` so ``apply_diff('all')`` and
  ``'additions_only'`` cannot silently re-enable them or delete them.

3.9 covered here:

- ``extract_device_names_from_plan`` unions in device names bound via
  ``@parameter_annotation_decorator`` defaults, so a plan submitted without
  arguments whose parameters have decorator-defined defaults locks those
  defaults too.
- ``lock_devices_for_plan`` filters the extracted device names against the
  active config-service registry, logging profile-only or disabled devices
  and skipping them from the lock request instead of 404-blocking the whole
  plan. A registry-lookup failure at lock time is surfaced as a
  ConfigServiceError so the caller aborts the plan (no silent over-lock
  against a stale set).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from queueserver_service.manager.config_service import (
    ConfigServiceClient,
    ConfigServiceError,
    ConfigServiceSettings,
    ConfigServiceState,
    compute_diff,
    sync_devices_on_env_open,
)
from queueserver_service.manager.config_service_coordinator import (
    ConfigServiceCoordinator,
)
from queueserver_service.manager.profile_ops import extract_device_names_from_plan

# ---------------------------------------------------------------------------
# 3.8 — get_instantiation_specs threads active_only through
# ---------------------------------------------------------------------------


def _record_requests():
    """Return (client, seen) where ``seen`` is a list of (path, params) tuples
    populated as the client makes requests via an httpx MockTransport."""
    seen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json={})

    settings = ConfigServiceSettings(enabled=True, url="http://cfg")
    client = ConfigServiceClient(settings)
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://cfg"
    )
    return client, seen


@pytest.mark.asyncio
async def test_get_instantiation_specs_defaults_to_active_only_true():
    client, seen = _record_requests()
    try:
        await client.get_instantiation_specs()
    finally:
        await client.aclose()
    assert seen == [("/api/v1/devices/instantiation", {"active_only": "true"})]


@pytest.mark.asyncio
async def test_get_instantiation_specs_active_only_false_passes_through():
    client, seen = _record_requests()
    try:
        await client.get_instantiation_specs(active_only=False)
    finally:
        await client.aclose()
    assert seen == [("/api/v1/devices/instantiation", {"active_only": "false"})]


# ---------------------------------------------------------------------------
# 3.8 — all-disabled registry must not trigger bootstrap
# ---------------------------------------------------------------------------


def _seq_responses(responses):
    """Build an httpx MockTransport handler that returns ``responses`` in order."""
    it = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        try:
            return next(it)
        except StopIteration as exc:
            raise AssertionError(
                f"unexpected extra request: {request.method} {request.url.path}"
            ) from exc

    return handler


def _client_with(responses):
    settings = ConfigServiceSettings(enabled=True, url="http://cfg")
    client = ConfigServiceClient(settings)
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(_seq_responses(responses)), base_url="http://cfg"
    )
    return client


@pytest.mark.asyncio
async def test_sync_devices_on_env_open_all_disabled_registry_does_not_bootstrap():
    """The regression: a registry containing only disabled devices returns an
    empty ``prefetched_info`` (active-only fetch) but ``/devices-info`` (all
    devices) is NON-empty. The sync must NOT re-run bootstrap on that
    registry — doing so would re-upsert every worker device with
    ``active=True`` and silently re-enable them."""
    changes_payload = {
        "current_version": 5,
        "service_epoch": "2026-07",
        "reset_occurred": False,
        "changes": [],
    }
    client = _client_with(
        [
            # /devices-info: registry is NOT empty (a disabled device exists),
            # so bootstrap must be skipped.
            httpx.Response(200, json={"m1": {"name": "m1", "active": False}}),
            # /devices/changes: cursor capture.
            httpx.Response(200, json=changes_payload),
        ]
    )
    try:
        async with client:
            state = await sync_devices_on_env_open(
                client,
                expected_device_names=["m1"],
                device_data={"m1": {"metadata": {"name": "m1"}, "spec": {"x": 1}}},
                prefetched_info={},  # active-only fetch returned nothing
            )
    finally:
        # Client is already closed by the `async with`; no double-close.
        pass
    assert state == ConfigServiceState(cursor=5, epoch="2026-07")


# ---------------------------------------------------------------------------
# 3.8 — compute_diff routes disabled registry entries into the new bucket
# ---------------------------------------------------------------------------


def _payload(spec):
    return {"metadata": {}, "spec": spec}


def test_compute_diff_disabled_registry_entry_excluded_from_added_removed_modified():
    """Every scenario for a device with ``spec.active is False`` in the registry:

    - present in worker with a matching spec → ``disabled`` only (not ``modified``);
    - present in worker with a differing spec → ``disabled`` only (not ``modified``);
    - absent from worker → ``disabled`` only (not ``removed``);

    In all three cases the device must not appear in a bucket that
    ``apply_diff('all')`` acts on."""
    disabled_spec = {"device_class": "ophyd.Signal", "args": [], "kwargs": {}, "active": False}
    worker_data = {
        "match_disabled": _payload(disabled_spec),
        # Different spec but disabled in registry — must still land in
        # ``disabled``, not ``modified``.
        "differing_disabled": _payload(
            {"device_class": "ophyd.EpicsSignal", "args": ["PV:X"], "kwargs": {}}
        ),
    }
    registry_specs = {
        "match_disabled": disabled_spec,
        "differing_disabled": disabled_spec,
        "vanished_disabled": disabled_spec,  # not in worker
    }
    d = compute_diff(worker_data, registry_specs)
    assert d.disabled == sorted(
        ["match_disabled", "differing_disabled", "vanished_disabled"]
    )
    assert d.added == []
    assert d.removed == []
    assert d.modified == []


def test_compute_diff_active_registry_entries_still_diff_normally():
    """Active-registry devices still go through the classic add/remove/modify
    logic — the disabled bucket only intercepts inactive entries."""
    worker_data = {
        "new": _payload({"device_class": "ophyd.Signal", "args": [], "kwargs": {}}),
        "changed": _payload({"device_class": "ophyd.Signal", "args": [1], "kwargs": {}}),
    }
    registry_specs = {
        "changed": {"device_class": "ophyd.Signal", "args": [], "kwargs": {}, "active": True},
        "gone": {"device_class": "ophyd.Signal", "args": [], "kwargs": {}, "active": True},
    }
    d = compute_diff(worker_data, registry_specs)
    assert d.added == ["new"]
    assert d.removed == ["gone"]
    assert [m["name"] for m in d.modified] == ["changed"]
    assert d.disabled == []


def test_compute_diff_to_dict_includes_disabled_bucket():
    d = compute_diff({}, {"x": {"active": False}})
    body = d.to_dict()
    assert body["disabled"] == ["x"]
    assert body["added"] == []
    assert body["removed"] == []
    assert body["modified"] == []


# ---------------------------------------------------------------------------
# 3.9 — extract_device_names_from_plan visits decorator defaults
# ---------------------------------------------------------------------------


_DEVICE_TREE = {
    "det1": {"components": {}},
    "det2": {"components": {}},
    "motor1": {"components": {"velocity": {}}},
}


def test_extract_names_includes_decorator_default_list_of_devices():
    """A plan submitted with NO args/kwargs whose ``detectors`` parameter has
    a decorator default of ``[det1, det2]`` locks det1 + det2. Pre-3.9 the
    scan only visited args/kwargs and missed both."""
    plan = {"name": "count", "args": [], "kwargs": {}}
    existing_plans = {
        "count": {
            "parameters": [
                {
                    "name": "detectors",
                    "default": "['det1', 'det2']",
                    "default_defined_in_decorator": True,
                }
            ]
        }
    }
    result = extract_device_names_from_plan(
        plan, existing_devices=_DEVICE_TREE, existing_plans=existing_plans
    )
    assert result == ["det1", "det2"]


def test_extract_names_includes_decorator_default_single_device_string():
    plan = {"name": "count", "args": [], "kwargs": {}}
    existing_plans = {
        "count": {
            "parameters": [
                {
                    "name": "detectors",
                    "default": "'det1'",
                    "default_defined_in_decorator": True,
                }
            ]
        }
    }
    result = extract_device_names_from_plan(
        plan, existing_devices=_DEVICE_TREE, existing_plans=existing_plans
    )
    assert result == ["det1"]


def test_extract_names_skips_non_decorator_defaults():
    """Only ``default_defined_in_decorator=True`` defaults are visited —
    regular Python defaults live in the function header and aren't
    re-serialized into the plan description in a form we can safely eval."""
    plan = {"name": "count", "args": [], "kwargs": {}}
    existing_plans = {
        "count": {
            "parameters": [
                {"name": "detectors", "default": "['det1']"},
                {
                    "name": "num",
                    "default": "5",
                    "default_defined_in_decorator": True,
                },
            ]
        }
    }
    result = extract_device_names_from_plan(
        plan, existing_devices=_DEVICE_TREE, existing_plans=existing_plans
    )
    assert result == []


def test_extract_names_swallows_undecodable_decorator_defaults():
    """A decorator default that isn't a literal (e.g. a call expression) is
    not a device reference; failing to ``literal_eval`` it must not block
    the plan — just skip that parameter."""
    plan = {"name": "count", "args": [], "kwargs": {}}
    existing_plans = {
        "count": {
            "parameters": [
                {
                    "name": "detectors",
                    "default": "some_factory()",
                    "default_defined_in_decorator": True,
                },
                {
                    "name": "extra",
                    "default": "'det2'",
                    "default_defined_in_decorator": True,
                },
            ]
        }
    }
    result = extract_device_names_from_plan(
        plan, existing_devices=_DEVICE_TREE, existing_plans=existing_plans
    )
    assert result == ["det2"]


def test_extract_names_over_locks_by_visiting_defaults_regardless_of_binding():
    """Contract: over-locking is the safe direction. When the caller supplies
    ``detectors=[det2]``, we STILL visit the decorator default ``[det1]`` and
    add det1 too. The manager doesn't reproduce the worker's positional
    binding logic; matching the args/kwargs pass keeps the design simple.
    """
    plan = {"name": "count", "args": [], "kwargs": {"detectors": ["det2"]}}
    existing_plans = {
        "count": {
            "parameters": [
                {
                    "name": "detectors",
                    "default": "['det1']",
                    "default_defined_in_decorator": True,
                }
            ]
        }
    }
    result = extract_device_names_from_plan(
        plan, existing_devices=_DEVICE_TREE, existing_plans=existing_plans
    )
    assert result == ["det1", "det2"]


def test_extract_names_ignores_missing_existing_plans_entry():
    """Plan not present in ``existing_plans`` → no decorator-default pass; the
    args/kwargs scan still runs (backward compatible with the two-arg call
    signature)."""
    plan = {"name": "not_registered", "args": [["det1"]], "kwargs": {}}
    result = extract_device_names_from_plan(
        plan, existing_devices=_DEVICE_TREE, existing_plans={}
    )
    assert result == ["det1"]


# ---------------------------------------------------------------------------
# 3.9 — lock_devices_for_plan filters against active registry membership
# ---------------------------------------------------------------------------


class _RecordingCoordClient:
    """FakeClient variant that records get_instantiation_specs calls so tests
    can assert on the query mode + the filtered lock set."""

    def __init__(self, *, registry_active_names=(), get_specs_raises=None):
        self.registry_active_names = list(registry_active_names)
        self.get_specs_raises = get_specs_raises
        self.get_specs_calls: list[bool] = []
        self.locked: list = []
        self.unlocked: list = []

    async def get_instantiation_specs(self, *, active_only=True):
        self.get_specs_calls.append(active_only)
        if self.get_specs_raises is not None:
            raise self.get_specs_raises
        return {name: {"device_class": "ophyd.Signal"} for name in self.registry_active_names}

    async def lock_devices(self, device_names, *, item_id, plan_name):
        self.locked.append((list(device_names), item_id, plan_name))
        return {"lock_epoch": "e", "lease_ttl_seconds": 0.0, "expires_at": None}

    async def unlock_devices(self, device_names, *, item_id):
        self.unlocked.append((list(device_names), item_id))
        return {}

    async def aclose(self):
        pass


class _CoordHost:
    def __init__(self, existing_devices=None, existing_plans=None):
        self._existing_devices = existing_devices or {}
        self._existing_plans = existing_plans or {}

    @property
    def existing_devices(self):
        return self._existing_devices

    @property
    def existing_plans(self):
        return self._existing_plans

    async def worker_update_device_overlay(self, upserts, deletes, *, replace):
        return True, ""

    async def reload_lists_from_worker(self):
        return True


def _make_coord(client, *, host=None):
    settings = ConfigServiceSettings(enabled=True, url="http://cfg", lock_scope="plan")
    coord = ConfigServiceCoordinator(settings, host=host or _CoordHost())
    coord._client = client
    return coord


def test_lock_devices_for_plan_filters_profile_only_devices_out(monkeypatch, caplog):
    """Names in the plan but NOT in the active registry are excluded from the
    lock request (no 404 blast) and logged as a warning. The remaining
    registered devices are locked normally."""
    import queueserver_service.manager.config_service_coordinator as coord_mod

    monkeypatch.setattr(
        coord_mod, "extract_device_names_from_plan",
        lambda item, *, existing_devices, existing_plans=None: [
            "det_registered", "det_profile_only"
        ],
    )
    client = _RecordingCoordClient(registry_active_names=["det_registered"])
    coord = _make_coord(client)

    with caplog.at_level("WARNING", logger="queueserver_service.manager.config_service_coordinator"):
        asyncio.run(
            coord.lock_devices_for_plan(
                {"name": "count", "item_uid": "u1", "args": [], "kwargs": {}}
            )
        )

    assert client.get_specs_calls == [True]  # active-only registry membership
    assert client.locked == [(["det_registered"], "u1", "count")]
    assert coord._locked_devices == ["det_registered"]
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("det_profile_only" in msg for msg in warnings)


def test_lock_devices_for_plan_no_lock_when_all_devices_profile_only(monkeypatch, caplog):
    """When EVERY extracted device is filtered out, no lock request is made
    (previously the manager would 404 and abort the plan; now the plan
    proceeds with a warning that coordination is not enforced)."""
    import queueserver_service.manager.config_service_coordinator as coord_mod

    monkeypatch.setattr(
        coord_mod, "extract_device_names_from_plan",
        lambda item, *, existing_devices, existing_plans=None: ["det_profile_only"],
    )
    client = _RecordingCoordClient(registry_active_names=[])
    coord = _make_coord(client)

    with caplog.at_level("WARNING", logger="queueserver_service.manager.config_service_coordinator"):
        asyncio.run(
            coord.lock_devices_for_plan(
                {"name": "count", "item_uid": "u2", "args": [], "kwargs": {}}
            )
        )

    assert client.locked == []
    assert coord._locked_item_id == ""


def test_lock_devices_for_plan_filters_out_disabled_registry_entries(monkeypatch):
    """A device present in the registry but ``active=false`` is excluded from
    the lock set — the config-service would reject the request with 409
    (disabled) otherwise, and re-enabling it silently at lock time is not
    something we want. Only active registry entries pass the filter."""
    import queueserver_service.manager.config_service_coordinator as coord_mod

    monkeypatch.setattr(
        coord_mod, "extract_device_names_from_plan",
        lambda item, *, existing_devices, existing_plans=None: ["det_active", "det_disabled"],
    )
    # get_instantiation_specs(active_only=True) only returns active devices,
    # so det_disabled naturally doesn't appear.
    client = _RecordingCoordClient(registry_active_names=["det_active"])
    coord = _make_coord(client)

    asyncio.run(
        coord.lock_devices_for_plan(
            {"name": "count", "item_uid": "u3", "args": [], "kwargs": {}}
        )
    )

    assert client.locked == [(["det_active"], "u3", "count")]


def test_lock_devices_for_plan_registry_lookup_failure_propagates(monkeypatch):
    """A registry-lookup failure at per-plan-lock time is a coordination
    outage, not a lock decision — raise so the caller aborts the plan
    (matches every other config-service failure) rather than falling back
    to an over-lock against a stale set."""
    import queueserver_service.manager.config_service_coordinator as coord_mod

    monkeypatch.setattr(
        coord_mod, "extract_device_names_from_plan",
        lambda item, *, existing_devices, existing_plans=None: ["det1"],
    )
    client = _RecordingCoordClient(
        get_specs_raises=RuntimeError("simulated config-service outage")
    )
    coord = _make_coord(client)

    with pytest.raises(ConfigServiceError, match="registry membership"):
        asyncio.run(
            coord.lock_devices_for_plan(
                {"name": "count", "item_uid": "u4", "args": [], "kwargs": {}}
            )
        )
    assert client.locked == []


def test_lock_devices_for_plan_threads_existing_plans_to_extractor(monkeypatch):
    """The coordinator must pass the manager's existing_plans dict to
    ``extract_device_names_from_plan`` so the decorator-default union runs.
    (The 3.9 code paths depend on both this wiring AND the extractor
    change; this test pins the wiring.)"""
    import queueserver_service.manager.config_service_coordinator as coord_mod

    seen: dict = {}

    def _capturing_extract(item, *, existing_devices, existing_plans=None):
        seen["existing_plans"] = existing_plans
        return []

    monkeypatch.setattr(coord_mod, "extract_device_names_from_plan", _capturing_extract)
    plans = {"count": {"parameters": [{"name": "d", "default": "'det1'"}]}}
    coord = _make_coord(
        _RecordingCoordClient(), host=_CoordHost(existing_plans=plans)
    )

    asyncio.run(
        coord.lock_devices_for_plan(
            {"name": "count", "item_uid": "u5", "args": [], "kwargs": {}}
        )
    )

    assert seen["existing_plans"] is plans
