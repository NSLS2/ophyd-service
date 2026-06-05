"""
Side-A integration: direct-control's config-service clients against a REAL
in-process configuration_service.

Unlike the unit tests that stub the registry (``tests/conftest.py::_StubRegistry``)
or drive a client with ``httpx.MockTransport``, this module boots a real
``configuration_service.create_app()`` in-process via ``httpx.ASGITransport`` +
``asgi_lifespan.LifespanManager`` and points direct-control's ``RegistryClient``
and ``CoordinationClient`` at it. The clients therefore speak the *actual*
config-service REST contract -- route strings, 404 semantics, and the
``PVStatusResponse`` / ``DeviceStatusResponse`` field shapes that drive
``_map_lock_status`` -- which the mocks cannot pin.

The injection point is the clients' lazy ``self._client is None`` seam: assigning
``_client`` before first use needs no production change.

No EPICS is involved -- configuration_service is a pure ASGI app and these tests
never touch direct-control's monitoring/pyepics layer. (The session-scoped IOC
fixture in ``conftest.py`` still runs because it is ``autouse``, but nothing here
uses it.)
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio

pytest.importorskip("configuration_service")
pytest.importorskip("asgi_lifespan")

from asgi_lifespan import LifespanManager  # noqa: E402
from configuration_service.config import Settings as CSSettings  # noqa: E402
from configuration_service.main import create_app  # noqa: E402

from direct_control.config import Settings as DCSettings  # noqa: E402
from direct_control.coordination_client import CoordinationClient  # noqa: E402
from direct_control.models import DeviceLockStatus  # noqa: E402
from direct_control.registry_client import (  # noqa: E402
    RegistryClient,
    RegistryValidationError,
)

# The mock registry (``use_mock_data=True``) ships device ``sample_x`` with these
# component PVs; verified against the real app. Keeping them as constants makes
# the contract the test pins explicit.
_DEVICE = "sample_x"
_PV = "BL01:SAMPLE:X.RBV"


def _dc_settings() -> DCSettings:
    # The URL is irrelevant: the fixture pre-injects an ASGI-backed client so no
    # real socket is opened. It is supplied only because the field is required.
    return DCSettings(configuration_service_url="http://testserver")


@pytest_asyncio.fixture
async def side_a(tmp_path) -> AsyncIterator[SimpleNamespace]:
    """A real config-service app plus direct-control clients wired to it via ASGI.

    Yields a namespace with ``registry`` (RegistryClient), ``coord``
    (CoordinationClient), and ``raw`` (a plain httpx client for seeding the
    write side of the edge, e.g. POST /devices/lock).
    """
    cs_settings = CSSettings(
        use_mock_data=True,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'cs.db'}",
    )
    cs_app = create_app(cs_settings)

    # LifespanManager is required: httpx.ASGITransport does not run the ASGI
    # lifespan, and without startup the app's table creation + mock seed (and
    # the get_state dependency) never happen.
    async with LifespanManager(cs_app):
        transport = httpx.ASGITransport(app=cs_app)

        registry = RegistryClient(_dc_settings())
        coord = CoordinationClient(_dc_settings())
        registry._client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
        coord._client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
        raw = httpx.AsyncClient(transport=transport, base_url="http://testserver")

        try:
            yield SimpleNamespace(registry=registry, coord=coord, raw=raw)
        finally:
            await registry.cleanup()
            await coord.cleanup()
            await raw.aclose()


async def test_validate_device_known_and_unknown(side_a):
    """validate_device speaks GET /api/v1/devices/{name}: 200 ok, real 404 raises."""
    await side_a.registry.validate_device(_DEVICE)  # no raise

    with pytest.raises(RegistryValidationError):
        await side_a.registry.validate_device("no_such_device")


async def test_validate_pv_known_and_unknown(side_a):
    """validate_pv speaks GET /api/v1/pvs/{pv}: known 200 ok, unknown real 404 raises."""
    await side_a.registry.validate_pv(_PV)  # no raise

    with pytest.raises(RegistryValidationError):
        await side_a.registry.validate_pv("NO:SUCH:PV")


async def test_get_owning_device_resolves_real_owner(side_a):
    """PVStatusResponse.device_name resolves a leaf PV to its owning device."""
    assert await side_a.registry.get_owning_device(_PV) == _DEVICE


async def test_validate_pv_caches_positive_result(side_a):
    """A positive validate_pv result is cached so the repeat needs no round-trip."""
    assert _PV not in side_a.registry._pv_cache
    await side_a.registry.validate_pv(_PV)
    cached_exists = side_a.registry._pv_cache[_PV][0]
    assert cached_exists is True


async def test_lock_status_available_then_locked(side_a):
    """The real lock write -> status read round-trip across the config edge.

    Exercises ``_map_lock_status`` against the real DeviceStatusResponse:
    enabled+unlocked -> AVAILABLE, then locked -> LOCKED with locked_by set to
    the plan holding the lock.
    """
    coord = side_a.coord

    pre = await coord.check_device_available(_DEVICE)
    assert pre.status is DeviceLockStatus.AVAILABLE
    assert pre.device_available is True
    assert pre.locked_by is None

    resp = await side_a.raw.post(
        "/api/v1/devices/lock",
        json={"device_names": [_DEVICE], "item_id": "item-001", "plan_name": "count"},
    )
    assert resp.status_code == 200

    post = await coord.check_device_available(_DEVICE)
    assert post.status is DeviceLockStatus.LOCKED
    assert post.device_available is False
    assert post.locked_by == "count"


async def test_unregistered_name_maps_to_available(side_a):
    """An unregistered name 404s on /status and maps to AVAILABLE.

    Direct-control must not block writes for raw PV names that have no
    device-level lock concept (the 404 path in check_device_available).
    """
    status = await side_a.coord.check_device_available("definitely_not_a_device")
    assert status.status is DeviceLockStatus.AVAILABLE
    assert status.device_available is True
