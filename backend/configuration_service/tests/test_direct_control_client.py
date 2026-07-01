"""Unit tests for ``DirectControlClient`` response-shape validation.

Uses ``httpx.MockTransport`` to drive the client against synthetic
responses without standing up a real direct-control instance. Focus:
the defensive checks that turn a malformed reply (truncated JSON,
wrong-length results, missing keys) into ``DirectControlUnavailable``
so the resolver marks every deferred slot as ``enrichment_unavailable``
instead of silently dropping rows.
"""

from __future__ import annotations

import httpx
import pytest

from configuration_service.direct_control_client import (
    DirectControlClient,
    DirectControlUnavailable,
    EnrichmentSpec,
)

# A single spec is enough for most checks; pick a stable one.
SPEC = EnrichmentSpec(
    device_class_path="some.module.Cls",
    prefix="X:Y",
    sub_path="leaf",
)


def _client_with_handler(handler):
    """Build a DirectControlClient whose transport is the given handler.

    httpx's MockTransport routes every request through ``handler`` (which
    returns a synthetic ``httpx.Response``), so the client never touches
    a network.
    """
    client = DirectControlClient(base_url="http://stub", timeout=1.0)
    # Swap the AsyncClient for one backed by MockTransport. We keep the
    # base_url on the new client so the relative POST resolves correctly.
    client._client = httpx.AsyncClient(  # type: ignore[attr-defined]
        transport=httpx.MockTransport(handler), base_url="http://stub"
    )
    return client


@pytest.mark.asyncio
async def test_enrich_happy_path():
    """Well-formed response → list of EnrichmentResult in caller order."""

    def handler(request):
        return httpx.Response(
            200,
            json={
                "results": [
                    {"ok": True, "pv_name": "X:Y.leaf"},
                ]
            },
        )

    client = _client_with_handler(handler)
    results = await client.enrich([SPEC])
    assert len(results) == 1
    assert results[0].ok is True
    assert results[0].pv_name == "X:Y.leaf"
    await client.aclose()


@pytest.mark.asyncio
async def test_enrich_non_200_status_raises():
    def handler(request):
        return httpx.Response(503, text="upstream gone")

    client = _client_with_handler(handler)
    with pytest.raises(DirectControlUnavailable, match="503"):
        await client.enrich([SPEC])
    await client.aclose()


@pytest.mark.asyncio
async def test_enrich_malformed_json_raises():
    def handler(request):
        # Not JSON at all (e.g. a reverse proxy stuffing HTML in front).
        return httpx.Response(
            200,
            text="<html>this is not json</html>",
            headers={"content-type": "text/html"},
        )

    client = _client_with_handler(handler)
    with pytest.raises(DirectControlUnavailable, match="malformed body"):
        await client.enrich([SPEC])
    await client.aclose()


@pytest.mark.asyncio
async def test_enrich_missing_results_key_raises():
    def handler(request):
        return httpx.Response(200, json={"unexpected": []})

    client = _client_with_handler(handler)
    with pytest.raises(DirectControlUnavailable, match="malformed body"):
        await client.enrich([SPEC])
    await client.aclose()


@pytest.mark.asyncio
async def test_enrich_results_wrong_length_raises():
    """Server returned 2 results for 3 requests — refuse rather than
    silently dropping the third deferred slot."""

    def handler(request):
        return httpx.Response(
            200,
            json={
                "results": [
                    {"ok": True, "pv_name": "X:Y.a"},
                    {"ok": True, "pv_name": "X:Y.b"},
                ]
            },
        )

    specs = [SPEC, SPEC, SPEC]
    client = _client_with_handler(handler)
    with pytest.raises(DirectControlUnavailable, match="2 results for 3 requests"):
        await client.enrich(specs)
    await client.aclose()


@pytest.mark.asyncio
async def test_enrich_results_not_a_list_raises():
    def handler(request):
        return httpx.Response(200, json={"results": "this should be a list"})

    client = _client_with_handler(handler)
    with pytest.raises(DirectControlUnavailable, match="str results"):
        await client.enrich([SPEC])
    await client.aclose()


@pytest.mark.asyncio
async def test_enrich_transport_error_raises():
    """Network-level failure (timeout, refused) maps to DirectControlUnavailable."""

    def handler(request):
        raise httpx.ConnectError("connection refused")

    client = _client_with_handler(handler)
    with pytest.raises(DirectControlUnavailable, match="unreachable"):
        await client.enrich([SPEC])
    await client.aclose()
