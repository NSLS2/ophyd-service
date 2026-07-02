"""Global WebSocket connection-cap enforcement (settings.ws_max_connections).

The cap is enforced in main._reject_if_ws_capacity_reached by summing the live
connection count across all four socket managers (pv / device / camera / tiff)
and rejecting new sockets with WS close code 1013 once the limit is hit. These
unit tests drive that helper directly with fakes — no IOC or real CA needed.
"""

import types

import pytest

import direct_control.main as m


class _FakeManager:
    """Stands in for a socket manager, exposing only connection_count."""

    def __init__(self, count: int) -> None:
        self._count = count

    @property
    def connection_count(self) -> int:
        return self._count


class _FakeWebSocket:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    async def accept(self) -> None:
        self.events.append(("accept",))

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.events.append(("close", code, reason))


def _install_managers(monkeypatch, *, limit, pv=0, device=0, camera=0, tiff=0):
    monkeypatch.setattr(
        m.app.state, "settings", types.SimpleNamespace(ws_max_connections=limit), raising=False
    )
    monkeypatch.setattr(m.app.state, "ws_manager", _FakeManager(pv), raising=False)
    monkeypatch.setattr(m.app.state, "device_ws_manager", _FakeManager(device), raising=False)
    monkeypatch.setattr(m.app.state, "camera_ws_manager", _FakeManager(camera), raising=False)
    monkeypatch.setattr(m.app.state, "tiff_ws_manager", _FakeManager(tiff), raising=False)


@pytest.mark.asyncio
async def test_rejects_when_total_at_capacity(monkeypatch):
    """At the limit, the socket is accepted-then-closed with 1013 and rejected."""
    _install_managers(monkeypatch, limit=3, pv=1, device=1, camera=1, tiff=0)  # total 3 == limit
    ws = _FakeWebSocket()
    rejected = await m._reject_if_ws_capacity_reached(ws)
    assert rejected is True
    assert ws.events[0] == ("accept",)
    assert ws.events[1][0] == "close"
    assert ws.events[1][1] == 1013


@pytest.mark.asyncio
async def test_allows_when_under_capacity(monkeypatch):
    """Below the limit, the helper returns False and does not touch the socket."""
    _install_managers(monkeypatch, limit=10, pv=2, device=1, camera=0, tiff=0)  # total 3 < limit
    ws = _FakeWebSocket()
    rejected = await m._reject_if_ws_capacity_reached(ws)
    assert rejected is False
    assert ws.events == []


@pytest.mark.asyncio
async def test_cap_is_global_across_all_socket_kinds(monkeypatch):
    """The cap counts every manager — image sockets alone can exhaust it."""
    _install_managers(monkeypatch, limit=2, pv=0, device=0, camera=1, tiff=1)  # total 2 == limit
    ws = _FakeWebSocket()
    assert await m._reject_if_ws_capacity_reached(ws) is True
