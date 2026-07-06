"""Regression tests for config-service overlay + device-sync robustness.

* The worker's device-overlay handler must apply upserts atomically
  (stage-then-commit): a failed device instantiation leaves the RE namespace
  exactly as it was, instead of half-applied while the command reports
  "rejected".
* The manager must send ``command_update_device_overlay`` with the long pipe
  timeout — the worker regenerates the whole plans/devices list, which exceeds
  the 0.5 s regular timeout and would otherwise abort the plan and stop the
  queue on every registry change.
* Config-service sync failures in the fire-and-forget periodic poll and in the
  manager restart path must be caught, surfaced in the ``config_service_sync_error``
  status field, and never allowed to escape (an escaping error crash-loops the
  manager on restart when config-service is unreachable).

The manager/worker are constructed via ``__new__`` (bypassing the
multiprocessing-heavy ``__init__``); only the attributes each method under test
touches are populated.
"""

from __future__ import annotations

import pytest

from queueserver_service.manager.manager import RunEngineManager
from queueserver_service.manager.worker import RunEngineWorker

# ----------------------------------------------------------------------------
# Worker overlay handler: stage-then-commit atomicity
# ----------------------------------------------------------------------------


def _bare_worker(namespace):
    w = RunEngineWorker.__new__(RunEngineWorker)
    # '_RE' is unset on a bare worker, so 're_state' returns None -> the
    # idle-state guard in the handler passes.
    w._re_namespace = namespace
    w._config_service_overlay_names = set()
    return w


def test_overlay_handler_instantiation_failure_leaves_namespace_unchanged(monkeypatch):
    import queueserver_service.manager.worker as worker_mod

    sentinel_existing = object()
    w = _bare_worker({"det_existing": sentinel_existing})
    original = dict(w._re_namespace)

    def fake_instantiate(spec):
        if spec == "BAD":
            raise RuntimeError("instantiation blew up")
        return f"device<{spec}>"

    monkeypatch.setattr(worker_mod, "instantiate_device_from_spec", fake_instantiate)

    result = w._command_update_device_overlay_handler(
        upserts={"dev_ok": "OK", "dev_bad": "BAD"},
        deletes=["det_existing"],
        replace=False,
    )

    assert result["status"] == "rejected"
    assert "instantiation blew up" in result["err_msg"]
    # Atomic: NOTHING was applied — the good upsert was not added and the
    # delete did not happen. Pre-fix the loop mutated the namespace in place, so
    # dev_ok would already be present and det_existing already gone.
    assert w._re_namespace == original
    assert w._config_service_overlay_names == set()


def test_overlay_handler_success_applies_all_mutations(monkeypatch):
    import queueserver_service.manager.worker as worker_mod

    w = _bare_worker({"det_existing": object(), "det_drop": object()})
    monkeypatch.setattr(
        worker_mod, "instantiate_device_from_spec", lambda spec: f"device<{spec}>"
    )
    # The list refresh runs after a successful commit; stub it out (no plans).
    w._refresh_lists_from_nspace = lambda: False

    result = w._command_update_device_overlay_handler(
        upserts={"dev_new": "SPEC"},
        deletes=["det_drop"],
        replace=False,
    )

    assert result["status"] == "accepted"
    assert w._re_namespace["dev_new"] == "device<SPEC>"
    assert "det_drop" not in w._re_namespace
    assert "det_existing" in w._re_namespace
    assert w._config_service_overlay_names == {"dev_new"}


# ----------------------------------------------------------------------------
# Manager overlay RPC: long timeout
# ----------------------------------------------------------------------------


class _FakeCommParams:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def send_msg(self, method, params=None, timeout=None):
        self.calls.append((method, params, timeout))
        return self.response


@pytest.mark.asyncio
async def test_overlay_rpc_uses_long_timeout():
    mgr = RunEngineManager.__new__(RunEngineManager)
    mgr._comm_to_worker_timeout_long = 10
    mgr._comm_to_worker = _FakeCommParams({"status": "accepted", "err_msg": ""})

    success, err = await mgr._worker_command_update_device_overlay(
        {"dev": "spec"}, [], replace=False
    )

    assert success is True
    assert err == ""
    method, params, timeout = mgr._comm_to_worker.calls[0]
    assert method == "command_update_device_overlay"
    # The long timeout, not the 0.5 s regular default — otherwise the overlay
    # times out after the worker already applied it, aborting the plan.
    assert timeout == mgr._comm_to_worker_timeout_long
    assert params == {"upserts": {"dev": "spec"}, "deletes": [], "replace": False}


# ----------------------------------------------------------------------------
# Guarded config-service sync: surfacing + no-escape
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guarded_sync_records_and_clears_error():
    mgr = RunEngineManager.__new__(RunEngineManager)
    mgr._config_service_sync_error = None
    updates = {"n": 0}
    mgr._status_update = lambda: updates.__setitem__("n", updates["n"] + 1)

    async def boom():
        raise RuntimeError("config-service unreachable")

    mgr._load_existing_plans_and_devices_from_worker = boom
    await mgr._sync_plans_devices_from_worker_guarded(context="periodic poll")
    assert mgr._config_service_sync_error == "config-service unreachable"
    assert updates["n"] == 1  # published once, on the transition into error

    async def ok():
        return True

    mgr._load_existing_plans_and_devices_from_worker = ok
    await mgr._sync_plans_devices_from_worker_guarded(context="periodic poll")
    assert mgr._config_service_sync_error is None
    assert updates["n"] == 2  # published again, on the transition back to clear


@pytest.mark.asyncio
async def test_guarded_sync_does_not_republish_status_when_healthy():
    """A healthy poll must not emit a status update every tick."""
    mgr = RunEngineManager.__new__(RunEngineManager)
    mgr._config_service_sync_error = None
    updates = {"n": 0}
    mgr._status_update = lambda: updates.__setitem__("n", updates["n"] + 1)

    async def ok():
        return True

    mgr._load_existing_plans_and_devices_from_worker = ok
    await mgr._sync_plans_devices_from_worker_guarded(context="periodic poll")
    await mgr._sync_plans_devices_from_worker_guarded(context="periodic poll")
    assert mgr._config_service_sync_error is None
    assert updates["n"] == 0  # value never changed -> no status churn


@pytest.mark.asyncio
async def test_guarded_sync_never_raises_so_startup_degrades():
    """The manager restart path awaits this directly, so it must never raise:
    an unreachable config-service must degrade (record + continue), not crash
    the startup coroutine and drive a watchdog crash-loop."""
    mgr = RunEngineManager.__new__(RunEngineManager)
    mgr._config_service_sync_error = None
    mgr._status_update = lambda: None

    async def boom():
        raise ConnectionError("registry down")

    mgr._load_existing_plans_and_devices_from_worker = boom
    # Must complete without raising.
    await mgr._sync_plans_devices_from_worker_guarded(context="manager restart")
    assert mgr._config_service_sync_error == "registry down"
