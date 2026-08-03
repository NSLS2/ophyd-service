"""Tests for ``POST /api/v1/devices/resolve``.

The endpoint looks devices up in the registry provider, instantiates
their ophyd classes, and walks the attribute chain to a leaf PV against
a live EPICS endpoint. We exercise it with small test classes wired to
the caproto test IOC (``IOC:counter``, ``IOC:m1``) and a spec-serving
registry stub, so both halves — registry lookup and live walk — run for
real.

The helper classes live at module scope so importlib can resolve them
by ``__module__ + __qualname__`` (the cache uses ``importlib.import_module``).
"""

from __future__ import annotations

import pytest
from ophyd import Component as Cpt
from ophyd import Device, EpicsSignal
from ophyd import FormattedComponent as FmtCpt

# ---------------------------------------------------------------------------
# Test ophyd classes wired to the caproto test IOC PVs
# ---------------------------------------------------------------------------


class _TestDeviceWithCpt(Device):
    """Simple device whose components are direct EpicsSignals on the test IOC.

    The instantiation prefix is ``IOC:`` so each component resolves to a
    real PV (``IOC:counter``, ``IOC:m1``) that the caproto test IOC
    serves. Without that, ophyd's lazy Component access would block on
    ``wait_for_connection``.
    """

    counter = Cpt(EpicsSignal, "counter")
    m1 = Cpt(EpicsSignal, "m1")


class _TestInnerWithFmtCpt(Device):
    """Sub-device whose FmtCpt references its parent's prefix.

    Mirrors the IOS pattern (``MirrorAxis.actuate``): the formatted
    suffix uses ``{self.parent.prefix}``, which only has meaning when
    the device is instantiated as a *child* of another Device — so we
    nest it inside ``_TestDeviceWithFmtCpt`` below.
    """

    # Default add_prefix=("suffix",) on FormattedComponent enables format
    # interpolation; {self.parent.prefix} resolves to the outer device's
    # prefix at instantiation time.
    counter_via_fmt = FmtCpt(EpicsSignal, "{self.parent.prefix}counter")


class _TestDeviceWithFmtCpt(Device):
    """Outer device that contains the FmtCpt-bearing inner.

    This is the canonical case live resolution exists to handle: the
    configuration service's static resolver can't fill in
    ``{self.parent.prefix}`` from the class alone and returns
    ``needs_enrichment``. Once instantiated, ophyd materializes the
    formatted suffix into the real PV (``IOC:counter``).
    """

    inner = Cpt(_TestInnerWithFmtCpt, "")


# ---------------------------------------------------------------------------
# Spec-serving registry stub
# ---------------------------------------------------------------------------


class _SpecRegistry:
    """Registry stub serving instantiation specs for the module's devices.

    ``dev_nospec`` exists but carries no class info (PV-gateway-only
    entry); unknown names return (None, None) like both real providers.
    """

    def __init__(self) -> None:
        from direct_control.models import InstantiationSpec

        self._specs = {
            "dev_cpt": InstantiationSpec(
                name="dev_cpt",
                device_class=f"{__name__}._TestDeviceWithCpt",
                args=["IOC:"],
            ),
            "dev_fmt": InstantiationSpec(
                name="dev_fmt",
                device_class=f"{__name__}._TestDeviceWithFmtCpt",
                args=["IOC:"],
            ),
            "dev_badclass": InstantiationSpec(
                name="dev_badclass",
                device_class="nonexistent_module.SomeClass",
                args=["IOC:"],
            ),
        }
        self._pvs = {
            "dev_cpt": {"counter": "IOC:counter", "m1": "IOC:m1"},
            "dev_fmt": {"inner.counter_via_fmt": "IOC:counter"},
            "dev_badclass": {"x": "IOC:counter"},
            "dev_nospec": {"raw": "IOC:counter"},
        }

    async def validate_pv(self, pv_name: str) -> None:
        return None

    async def validate_device(self, device_name: str) -> None:
        return None

    async def get_owning_device(self, pv_name: str):
        return None

    async def get_instantiation_spec(self, device_name: str):
        return self._specs.get(device_name)

    async def get_device_pvs(self, device_name: str):
        return self._pvs.get(device_name)

    async def cleanup(self) -> None:
        return None


class _DownRegistry(_SpecRegistry):
    """Registry stub whose lookups fail like an unreachable backend."""

    async def get_instantiation_spec(self, device_name: str):
        raise RuntimeError("Configuration service unavailable")

    async def get_device_pvs(self, device_name: str):
        raise RuntimeError("Configuration service unavailable")


@pytest.fixture
def resolve_client(client):
    """The standard client with the spec-serving registry stub installed."""
    from direct_control.main import get_registry_client

    client.app.dependency_overrides[get_registry_client] = lambda: _SpecRegistry()
    yield client


# ---------------------------------------------------------------------------
# Endpoint integration tests
# ---------------------------------------------------------------------------


def test_resolve_simple_cpt_walk(resolve_client):
    """Direct Component on a top-level device class — happy path."""
    r = resolve_client.post("/api/v1/devices/resolve", json={"addresses": ["dev_cpt.counter"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["resolved"]) == 1
    row = body["resolved"][0]
    assert row["ok"] is True, row
    assert row["outcome"] == "resolved"
    assert row["pv_name"] == "IOC:counter"
    assert row["address"] == "dev_cpt.counter"


def test_resolve_fmt_cpt_with_runtime_placeholder(resolve_client):
    """The case live resolution exists for: FmtCpt with {self.parent.prefix}.

    The configuration service's static resolver reports this address as
    ``needs_enrichment``; here the live device materializes the suffix
    and we read pvname off the leaf signal.
    """
    r = resolve_client.post(
        "/api/v1/devices/resolve",
        json={"addresses": ["dev_fmt.inner.counter_via_fmt"]},
    )
    assert r.status_code == 200, r.text
    row = r.json()["resolved"][0]
    assert row["ok"] is True, row
    assert row["pv_name"] == "IOC:counter"


def test_resolve_intermediate_device_returns_not_a_pv_leaf(resolve_client):
    """An address landing on an intermediate Device (not a leaf signal)
    should return not_a_pv_leaf — the walked attr exists but exposes
    neither ``pvname`` (classic ophyd) nor ``.source`` (ophyd-async).
    """
    r = resolve_client.post("/api/v1/devices/resolve", json={"addresses": ["dev_fmt.inner"]})
    assert r.status_code == 200
    row = r.json()["resolved"][0]
    assert row["ok"] is False
    assert row["outcome"] == "not_a_pv_leaf"
    assert "not a PV-bearing signal" in row["message"]


def test_resolve_unknown_sub_path_returns_no_such_attr(resolve_client):
    """A typo'd attribute chain should fail per-item with no_such_attr."""
    r = resolve_client.post(
        "/api/v1/devices/resolve", json={"addresses": ["dev_cpt.does_not_exist"]}
    )
    assert r.status_code == 200
    row = r.json()["resolved"][0]
    assert row["ok"] is False
    assert row["outcome"] == "no_such_attr"
    assert "does_not_exist" in row["message"]


def test_resolve_unknown_device_returns_device_not_found(resolve_client):
    r = resolve_client.post(
        "/api/v1/devices/resolve", json={"addresses": ["no_such_device.counter"]}
    )
    assert r.status_code == 200
    row = r.json()["resolved"][0]
    assert row["ok"] is False
    assert row["outcome"] == "device_not_found"
    assert "no_such_device" in row["message"]


def test_resolve_device_without_spec_returns_no_instantiation_spec(resolve_client):
    """A registered device with no class info can't be class-walked."""
    r = resolve_client.post("/api/v1/devices/resolve", json={"addresses": ["dev_nospec.raw"]})
    assert r.status_code == 200
    row = r.json()["resolved"][0]
    assert row["ok"] is False
    assert row["outcome"] == "no_instantiation_spec"


def test_resolve_bad_device_class_returns_instantiation_failed(resolve_client):
    """Bad import paths are caught and reported per item, not raised."""
    r = resolve_client.post("/api/v1/devices/resolve", json={"addresses": ["dev_badclass.x"]})
    assert r.status_code == 200
    row = r.json()["resolved"][0]
    assert row["ok"] is False
    assert row["outcome"] == "instantiation_failed"
    assert "nonexistent_module" in row["message"]


def test_resolve_registry_unavailable_fails_loud_per_item(client):
    """Registry backend down → registry_unavailable, never a fabricated
    static answer and never a 500."""
    from direct_control.main import get_registry_client

    client.app.dependency_overrides[get_registry_client] = lambda: _DownRegistry()
    r = client.post("/api/v1/devices/resolve", json={"addresses": ["dev_cpt.counter"]})
    assert r.status_code == 200
    row = r.json()["resolved"][0]
    assert row["ok"] is False
    assert row["outcome"] == "registry_unavailable"
    assert "unavailable" in row["message"].lower()


def test_resolve_memoizes_registry_lookups_per_device(client):
    """A batch addressing the same device repeatedly hits the registry once
    per lookup kind, not once per address (get_device_pvs has no client-side
    cache, so without the memo a large single-device batch multiplies HTTP
    calls against configuration_service)."""
    from direct_control.main import get_registry_client

    class _CountingRegistry(_SpecRegistry):
        def __init__(self):
            super().__init__()
            self.spec_calls = 0
            self.pvs_calls = 0

        async def get_instantiation_spec(self, device_name):
            self.spec_calls += 1
            return await super().get_instantiation_spec(device_name)

        async def get_device_pvs(self, device_name):
            self.pvs_calls += 1
            return await super().get_device_pvs(device_name)

    counting = _CountingRegistry()
    client.app.dependency_overrides[get_registry_client] = lambda: counting

    r = client.post(
        "/api/v1/devices/resolve",
        json={
            "addresses": ["dev_cpt.counter", "dev_cpt.m1", "dev_cpt.counter", "no_such_device.x"]
        },
    )
    assert r.status_code == 200
    rows = r.json()["resolved"]
    assert [row["ok"] for row in rows] == [True, True, True, False]
    # Two distinct heads -> two lookups of each kind, regardless of batch size.
    assert counting.spec_calls == 2
    assert counting.pvs_calls == 2


def test_resolve_batch_with_mixed_outcomes(resolve_client):
    """Best-effort per item, response rows in request order."""
    r = resolve_client.post(
        "/api/v1/devices/resolve",
        json={
            "addresses": [
                "dev_cpt.counter",
                "dev_cpt.bogus",
                "no_such_device",
                "dev_cpt.m1",
            ]
        },
    )
    assert r.status_code == 200
    rows = r.json()["resolved"]
    assert [row["ok"] for row in rows] == [True, False, False, True]
    assert [row["address"] for row in rows] == [
        "dev_cpt.counter",
        "dev_cpt.bogus",
        "no_such_device",
        "dev_cpt.m1",
    ]
    assert rows[0]["pv_name"] == "IOC:counter"
    assert rows[1]["outcome"] == "no_such_attr"
    assert rows[2]["outcome"] == "device_not_found"
    assert rows[3]["pv_name"] == "IOC:m1"


def test_resolve_cache_hit_reuses_device_instance(resolve_client):
    """Second call against the same device reuses the cached instance."""
    r1 = resolve_client.post("/api/v1/devices/resolve", json={"addresses": ["dev_cpt.counter"]})
    r2 = resolve_client.post("/api/v1/devices/resolve", json={"addresses": ["dev_cpt.m1"]})
    assert r1.status_code == 200 and r2.status_code == 200
    assert resolve_client.app.state.ophyd_cache.size() == 1


def test_resolve_empty_request_rejected(resolve_client):
    """Empty addresses list is a pydantic validation error."""
    r = resolve_client.post("/api/v1/devices/resolve", json={"addresses": []})
    assert r.status_code == 422


def test_resolve_max_length_enforced(resolve_client):
    """201-address request is rejected by the pydantic max_length guard."""
    r = resolve_client.post(
        "/api/v1/devices/resolve",
        json={"addresses": ["dev_cpt.counter" for _ in range(201)]},
    )
    assert r.status_code == 422


def test_resolve_extra_field_rejected(resolve_client):
    """extra='forbid' rejects unknown top-level keys."""
    r = resolve_client.post(
        "/api/v1/devices/resolve",
        json={"addresses": ["dev_cpt.counter"], "spurious": True},
    )
    assert r.status_code == 422


# Cache teardown is intentionally NOT done here. The service lifespan clears
# app.state.ophyd_cache on shutdown (see direct_control.main), and the
# `client` fixture re-runs the lifespan per test — so every test starts with a
# fresh, empty cache and instantiated devices' CA channels are released on
# teardown.
