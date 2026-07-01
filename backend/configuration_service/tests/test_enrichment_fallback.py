"""Tests for the resolver's enrichment fallback to direct-control.

When ``path_resolver.resolve()`` returns ``needs_enrichment`` (typically
a classic-ophyd ``FormattedComponent`` with a runtime placeholder),
configuration_service can ask direct-control to instantiate the device
live and return the resolved PV. This module exercises that flow with a
mocked direct-control client — no real direct-control instance needed.

Mocks plug into the closure-based container that ``create_app`` exposes
on ``app.state.direct_control_container`` and ``app.state.enrichment_cache_container``.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from configuration_service.direct_control_client import (
    DirectControlUnavailable,
    EnrichmentResult,
    EnrichmentSpec,
)

# ---------------------------------------------------------------------------
# Mock client + fixtures
# ---------------------------------------------------------------------------


@dataclass
class _MockCall:
    specs: list[EnrichmentSpec]


class _MockDirectControlClient:
    """In-process stand-in for ``DirectControlClient``.

    Tests configure ``next_response`` (a list of EnrichmentResult, one
    per spec the client receives) or ``raise_unavailable`` (mark the
    next call as a network failure). ``calls`` records every invocation
    so tests can assert call count + payload.
    """

    def __init__(self) -> None:
        self.next_response: list[EnrichmentResult] = []
        self.raise_unavailable: bool = False
        self.calls: list[_MockCall] = []

    async def enrich(self, specs: list[EnrichmentSpec]) -> list[EnrichmentResult]:
        self.calls.append(_MockCall(specs=list(specs)))
        if self.raise_unavailable:
            raise DirectControlUnavailable("simulated network failure")
        # Default to returning the configured response in order. If the
        # mock wasn't pre-configured for this batch size, return successes
        # named after the sub_path so the assertion-side has something
        # deterministic to check.
        if len(self.next_response) != len(specs):
            return [
                EnrichmentResult(ok=True, pv_name=f"ENRICHED:{spec.sub_path}") for spec in specs
            ]
        return self.next_response

    async def aclose(self) -> None:  # match the real client's shape
        pass


@pytest.fixture
def fmt_cpt_device_in_registry(client):
    """Register a device whose class uses a classic-ophyd FmtCpt with a
    placeholder so the static resolver returns ``needs_enrichment``.

    The class string points at ``test_classes.WithFmtCpt`` (defined in
    this package's test_classes module) so importlib can resolve it.
    """
    payload = {
        "metadata": {
            "name": "fmt_device",
            "device_label": "motor",
            "ophyd_class": "WithFmtCpt",
            "pvs": {},
            "labels": ["test"],
        },
        "instantiation_spec": {
            "name": "fmt_device",
            "device_class": "tests.test_classes.WithFmtCpt",
            "args": ["IOC:"],
            "kwargs": {"name": "fmt_device"},
            "active": True,
        },
    }
    r = client.post("/api/v1/devices", json=payload)
    assert r.status_code in (200, 201), r.text
    yield "fmt_device"


@pytest.fixture
def configure_enrichment(client):
    """Install a ``_MockDirectControlClient`` on the live app's container
    and return it so the test can drive its response."""
    mock = _MockDirectControlClient()
    client.app.state.direct_control_container["client"] = mock
    # Reset the enrichment cache between tests so cache-hit checks are
    # deterministic.
    client.app.state.enrichment_cache_container["cache"] = {}
    yield mock
    client.app.state.direct_control_container.pop("client", None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_client_configured_returns_needs_enrichment(client, fmt_cpt_device_in_registry):
    """When direct-control isn't wired up, needs_enrichment outcomes pass
    through unchanged (pre-feature behavior)."""
    # Ensure no client is configured on this fixture path.
    client.app.state.direct_control_container.pop("client", None)

    r = client.post(
        "/api/v1/devices/resolve",
        json={"addresses": ["fmt_device.inner.counter_via_fmt"]},
    )
    assert r.status_code == 200, r.text
    row = r.json()["resolved"][0]
    assert row["outcome"] == "needs_enrichment"
    assert row["ok"] is False


def test_enrichment_fills_in_needs_enrichment_outcomes(
    client, fmt_cpt_device_in_registry, configure_enrichment
):
    """With a client wired up, needs_enrichment items get enriched and
    returned as resolved."""
    configure_enrichment.next_response = [EnrichmentResult(ok=True, pv_name="IOC:counter")]

    r = client.post(
        "/api/v1/devices/resolve",
        json={"addresses": ["fmt_device.inner.counter_via_fmt"]},
    )
    assert r.status_code == 200, r.text
    row = r.json()["resolved"][0]
    assert row["outcome"] == "resolved"
    assert row["ok"] is True
    assert row["pv_name"] == "IOC:counter"
    # The client was called exactly once with the expected spec.
    assert len(configure_enrichment.calls) == 1
    sent_spec = configure_enrichment.calls[0].specs[0]
    assert sent_spec.device_class_path == "tests.test_classes.WithFmtCpt"
    assert sent_spec.prefix == "IOC:"
    assert sent_spec.sub_path == "inner.counter_via_fmt"


def test_enrichment_cache_skips_second_call(
    client, fmt_cpt_device_in_registry, configure_enrichment
):
    """A second identical address should hit the in-memory cache, not
    re-call direct-control."""
    configure_enrichment.next_response = [EnrichmentResult(ok=True, pv_name="IOC:counter")]

    address = "fmt_device.inner.counter_via_fmt"
    r1 = client.post("/api/v1/devices/resolve", json={"addresses": [address]})
    r2 = client.post("/api/v1/devices/resolve", json={"addresses": [address]})

    assert r1.json()["resolved"][0]["pv_name"] == "IOC:counter"
    assert r2.json()["resolved"][0]["pv_name"] == "IOC:counter"
    # Only the first request hit direct-control.
    assert len(configure_enrichment.calls) == 1


def test_direct_control_unavailable_yields_enrichment_unavailable(
    client, fmt_cpt_device_in_registry, configure_enrichment
):
    """Transport-level failure → mark every deferred item as
    enrichment_unavailable. The other items in the batch still resolve."""
    configure_enrichment.raise_unavailable = True

    # Mix one classic-resolvable address with one that needs enrichment so
    # we verify only the deferred one gets marked unavailable.
    r = client.post(
        "/api/v1/devices/resolve",
        json={
            "addresses": [
                "sample_x.user_setpoint",  # classic, resolves statically
                "fmt_device.inner.counter_via_fmt",  # defers, then fails
            ]
        },
    )
    assert r.status_code == 200, r.text
    rows = r.json()["resolved"]
    assert rows[0]["outcome"] == "resolved"
    assert rows[0]["pv_name"] == "BL01:SAMPLE:X.VAL"
    assert rows[1]["outcome"] == "enrichment_unavailable"
    assert "simulated network failure" in rows[1]["message"]


def test_direct_control_per_item_failure_yields_enrichment_unavailable(
    client, fmt_cpt_device_in_registry, configure_enrichment
):
    """If direct-control returns ok=false for a specific item (e.g. the
    IOC is down), the resolver surfaces enrichment_unavailable for that
    address — not the misleading needs_enrichment."""
    configure_enrichment.next_response = [
        EnrichmentResult(
            ok=False,
            error_type="InstantiationFailed",
            message="Could not connect to IOC",
        )
    ]

    r = client.post(
        "/api/v1/devices/resolve",
        json={"addresses": ["fmt_device.inner.counter_via_fmt"]},
    )
    assert r.status_code == 200, r.text
    row = r.json()["resolved"][0]
    assert row["outcome"] == "enrichment_unavailable"
    assert "InstantiationFailed" in row["message"]
    assert "Could not connect to IOC" in row["message"]


def test_enrichment_failure_not_cached(client, fmt_cpt_device_in_registry, configure_enrichment):
    """Per-item failures should NOT be cached — they may be transient
    (IOC restart) and we want the next request to retry."""
    configure_enrichment.next_response = [EnrichmentResult(ok=False, error_type="X", message="Y")]

    address = "fmt_device.inner.counter_via_fmt"
    client.post("/api/v1/devices/resolve", json={"addresses": [address]})
    # Now flip the mock to return success — a second request should hit
    # direct-control again (failure not cached) and pick up the new answer.
    configure_enrichment.next_response = [EnrichmentResult(ok=True, pv_name="IOC:counter")]
    r = client.post("/api/v1/devices/resolve", json={"addresses": [address]})

    assert r.json()["resolved"][0]["outcome"] == "resolved"
    assert r.json()["resolved"][0]["pv_name"] == "IOC:counter"
    assert len(configure_enrichment.calls) == 2  # both calls hit direct-control


def test_enrichment_batches_multiple_addresses(
    client, fmt_cpt_device_in_registry, configure_enrichment
):
    """Multiple needs_enrichment addresses in one request → single
    direct-control call with all of them."""
    configure_enrichment.next_response = [
        EnrichmentResult(ok=True, pv_name="IOC:counter"),
        EnrichmentResult(ok=True, pv_name="IOC:m1"),
    ]

    r = client.post(
        "/api/v1/devices/resolve",
        json={
            "addresses": [
                "fmt_device.inner.counter_via_fmt",
                "fmt_device.inner.m1_via_fmt",
            ]
        },
    )
    rows = r.json()["resolved"]
    assert [row["pv_name"] for row in rows] == ["IOC:counter", "IOC:m1"]
    # One round-trip, both specs in the same call.
    assert len(configure_enrichment.calls) == 1
    assert len(configure_enrichment.calls[0].specs) == 2
