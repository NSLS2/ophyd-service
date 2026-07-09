"""Device-PV resolution through the RegistryProvider abstraction.

The device-monitoring socket used to fetch a device's PVs with its own httpx
GET to ``configuration_service_url``. In file / standalone mode that URL is
``None``, so every device subscribe failed with ``upstream_unreachable`` — the
"fully featured standalone mode" was actually broken for the device socket.

These tests cover the new ``get_device_pvs`` on both registry providers and the
device socket resolving PVs in standalone (file) mode with no
configuration_service at all.
"""

from __future__ import annotations

import json

import httpx
import pytest

from direct_control.config import Settings
from direct_control.registry_client import RegistryClient
from direct_control.registry_file import FileRegistryProvider


def _write_registry(tmp_path, payload) -> str:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload))
    return str(path)


# ===== FileRegistryProvider (standalone mode) =====


async def test_file_provider_get_device_pvs(tmp_path):
    path = _write_registry(
        tmp_path,
        {
            "devices": [
                {"name": "m1", "pvs": ["BL:M1.RBV", "BL:M1.VAL"]},
                {"name": "no_pv_device", "pvs": []},
            ]
        },
    )
    provider = FileRegistryProvider(path)

    pvs = await provider.get_device_pvs("m1")
    # The file format has no logical component names, so component == PV.
    assert pvs == {"BL:M1.RBV": "BL:M1.RBV", "BL:M1.VAL": "BL:M1.VAL"}

    # A device with no PVs exists but returns an empty mapping (NOT None).
    assert await provider.get_device_pvs("no_pv_device") == {}

    # An unregistered device is None (distinct from "exists, no PVs").
    assert await provider.get_device_pvs("not_a_device") is None


async def test_file_provider_get_device_pvs_never_raises(tmp_path):
    """The file provider is loaded at startup, so lookups never raise
    (unlike the HTTP client, which raises RuntimeError when unreachable)."""
    path = _write_registry(tmp_path, {"devices": []})
    provider = FileRegistryProvider(path)
    assert await provider.get_device_pvs("anything") is None


# ===== RegistryClient (HTTP mode) =====


def _http_registry(handler) -> RegistryClient:
    client = RegistryClient(Settings())
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://stub"
    )
    return client


async def test_http_provider_get_device_pvs_200():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/devices/m1"
        return httpx.Response(200, json={"name": "m1", "pvs": {"readback": "BL:M1.RBV"}})

    client = _http_registry(handler)
    try:
        assert await client.get_device_pvs("m1") == {"readback": "BL:M1.RBV"}
    finally:
        await client.cleanup()


async def test_http_provider_get_device_pvs_404_is_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = _http_registry(handler)
    try:
        assert await client.get_device_pvs("nope") is None
    finally:
        await client.cleanup()


async def test_http_provider_get_device_pvs_5xx_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = _http_registry(handler)
    try:
        with pytest.raises(RuntimeError, match="HTTP 503"):
            await client.get_device_pvs("m1")
    finally:
        await client.cleanup()


async def test_http_provider_get_device_pvs_non_json_body_raises_runtime_error():
    """Malformed JSON body from a 200 response must surface as RuntimeError
    (the protocol's documented exception class) — not ValueError leaking to
    callers that only catch RuntimeError (device socket's ``_fetch_device_pvs``)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>oops</html>")

    client = _http_registry(handler)
    try:
        with pytest.raises(RuntimeError, match="malformed"):
            await client.get_device_pvs("m1")
    finally:
        await client.cleanup()


async def test_http_provider_get_device_pvs_non_mapping_pvs_raises_runtime_error():
    """A ``pvs`` value that isn't a mapping (e.g. list from a broken upstream)
    must surface as RuntimeError — not AttributeError from ``.items()``."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"name": "m1", "pvs": ["BL:M1.RBV"]})

    client = _http_registry(handler)
    try:
        with pytest.raises(RuntimeError, match="malformed"):
            await client.get_device_pvs("m1")
    finally:
        await client.cleanup()


async def test_http_provider_get_device_pvs_non_mapping_body_raises_runtime_error():
    """A JSON body that isn't an object (e.g. list root) must surface as
    RuntimeError — not AttributeError from ``.get(...)``."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not", "a", "mapping"])

    client = _http_registry(handler)
    try:
        with pytest.raises(RuntimeError, match="malformed"):
            await client.get_device_pvs("m1")
    finally:
        await client.cleanup()


# ===== device socket resolves PVs in standalone (file) mode =====


async def test_device_socket_fetches_pvs_in_standalone_mode(tmp_path):
    """The regression: the device socket must resolve a device's PVs from the
    file provider with no configuration_service. Before the fix this hit a
    ``None/api/v1/devices/...`` URL and returned ``upstream_unreachable``."""
    from direct_control.monitoring.device_websocket_manager import DeviceWebSocketManager

    path = _write_registry(
        tmp_path, {"devices": [{"name": "m1", "pvs": ["BL:M1.RBV", "BL:M1.VAL"]}]}
    )
    provider = FileRegistryProvider(path)

    # configuration_service_url is None in standalone mode — the manager must
    # never touch it. pv_monitor / device_controller are unused by the fetch.
    settings = Settings(
        configuration_service_url=None,
        registry_backend="file",
        registry_file_path=path,
    )
    mgr = DeviceWebSocketManager(
        pv_monitor=None,  # type: ignore[arg-type]
        device_controller=None,  # type: ignore[arg-type]
        settings=settings,
        registry_client=provider,
    )

    pvs, reason = await mgr._fetch_device_pvs("m1")
    assert reason is None
    assert pvs == {"BL:M1.RBV": "BL:M1.RBV", "BL:M1.VAL": "BL:M1.VAL"}

    missing, missing_reason = await mgr._fetch_device_pvs("ghost")
    assert missing is None
    assert missing_reason == "not_found"
