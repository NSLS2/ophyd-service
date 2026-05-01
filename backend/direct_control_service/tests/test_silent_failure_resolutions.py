"""
Regression tests for silent-failure-mode fixes from the 2026-05-01 audit.

Each test pins down a specific shape of the bug we just fixed: the API used
to report ``200 OK`` (or ``success=True``) on a path that was actually a
no-op or an error. A regression here would mean the silent-failure pattern
has crept back in.

Group by audit finding ID (S1, S2, ...) so it's clear what each test
guards. New tests added as we work through more findings — extend this
file rather than scattering them across other test files.
"""

from __future__ import annotations

import pytest


# ─── S1: device-method placeholders no longer return 200-OK / success=False ──
#
# Pre-fix: ``/stop`` and ``/execute`` returned ``200 OK`` with
# ``success=False`` deep inside the body. Operators saw 200 and assumed
# the device stopped; it didn't. After the fix, the controller raises
# ``NotImplementedError`` and the HTTP layer maps it to ``501 Not
# Implemented`` with a clear "requires ophyd integration" message.


def test_s1_stop_endpoint_returns_501_not_200_with_success_false(client):
    """``POST /api/v1/device/{name}/stop`` must surface unimplemented as 501.

    Pre-fix bug: 200 OK with ``success=False`` in the JSON body meant a
    safety-critical /stop call looked successful while doing nothing.
    """
    r = client.post("/api/v1/device/some_device/stop")
    assert r.status_code == 501, (
        f"expected 501 Not Implemented, got {r.status_code} {r.text!r}. "
        "If this is 200 with success=False, the silent-failure pattern is back."
    )
    detail = r.json()["detail"].lower()
    assert "not yet implemented" in detail
    assert "ophyd" in detail or "configuration service" in detail


def test_s1_execute_device_method_returns_501(client):
    """``POST /api/v1/device/execute`` must surface unimplemented as 501."""
    r = client.post(
        "/api/v1/device/execute",
        json={
            "device_name": "some_device",
            "method": "trigger",
            "args": [],
            "kwargs": {},
        },
    )
    assert r.status_code == 501, (
        f"expected 501, got {r.status_code} {r.text!r}"
    )
    assert "not yet implemented" in r.json()["detail"].lower()


def test_s1_nested_device_set_returns_501(client):
    """``POST /api/v1/device/{path}`` with method=set must surface unimplemented as 501."""
    r = client.post(
        "/api/v1/device/some_device.user_setpoint",
        json={"method": "set", "value": 1.0, "timeout": None},
    )
    assert r.status_code == 501
    detail = r.json()["detail"].lower()
    assert "not yet implemented" in detail


def test_s1_nested_device_read_returns_501(client):
    """``POST /api/v1/device/{path}`` with method=read must surface unimplemented as 501.

    Pre-fix the read branch returned a placeholder dict via 200 OK; a
    careless frontend would render that as a real value. Failing the read
    loudly forces the integration question to surface immediately.
    """
    r = client.post(
        "/api/v1/device/some_device.user_readback",
        json={"method": "read", "value": None, "timeout": None},
    )
    assert r.status_code == 501
    assert "not yet implemented" in r.json()["detail"].lower()


def test_s1_get_nested_device_value_returns_501(client):
    """``GET /api/v1/device/{path}/value`` (read-only) must also surface unimplemented as 501."""
    r = client.get("/api/v1/device/some_device.user_readback/value")
    assert r.status_code == 501
    assert "not yet implemented" in r.json()["detail"].lower()


def test_s1_stop_lock_gate_still_fires_before_not_implemented(client):
    """The coord gate must run before the not-implemented placeholder.

    A disabled or locked device should produce 409/423 (so the operator
    knows to re-enable / wait), NOT 501. Pre-fix this worked by
    coincidence because the placeholder was unreachable for blocked
    devices; pin it down so a future refactor can't accidentally invert
    the order.
    """
    from datetime import datetime
    from direct_control.models import CoordinationStatus, DeviceLockStatus

    class _DisabledStub:
        async def check_device_available(self, device_name: str) -> CoordinationStatus:
            return CoordinationStatus(
                device_available=False,
                locked_by=None,
                status=DeviceLockStatus.DISABLED,
                timestamp=datetime.now(),
            )

        async def is_service_available(self) -> bool:
            return True

        async def cleanup(self) -> None:
            return None

    app = client.app
    stub = _DisabledStub()
    app.state.coordination_client = stub
    app.state.device_controller.coordination = stub

    r = client.post("/api/v1/device/some_device/stop")
    assert r.status_code == 409, (
        f"expected 409 (disabled gate fires before not-implemented), got "
        f"{r.status_code} {r.text!r}"
    )


# ─── S2: set_pv no longer returns 200-OK with success=False on EPICS errors ──
#
# Pre-fix: ``set_pv`` caught every exception, returned
# ``PVSetResponse(success=False, value_set=<requested>)`` and the HTTP
# layer returned that as 200 OK. ``value_set=<requested>`` actively
# misled callers — it advertised the requested value as if it had been
# written. After the fix, errors raise ``ControlError`` and the HTTP
# layer maps to 500 (or a more specific status from the typed handlers
# above it).


def test_s2_set_pv_eipcs_failure_returns_5xx_not_200_with_success_false(client):
    """An EPICS write failure must surface as a 5xx, not 200-with-success=False.

    Drives the failure by writing to a PV name that the test IOC does not
    serve, with a short connection_timeout so the test stays fast. Pre-fix
    this returned 200 OK with ``success=False`` in the body — exactly the
    "looks healthy but isn't" shape the user has been burnt by.
    """
    r = client.post(
        "/api/v1/pv/set",
        json={
            "pv_name": "NOPE:DOES:NOT:EXIST",
            "value": 1.0,
            "wait": True,
            "timeout": 0.5,
            "connection_timeout": 0.5,
        },
    )
    assert r.status_code >= 500, (
        f"expected 5xx for an EPICS failure, got {r.status_code} {r.text!r}. "
        "Returning 200 with success=False is the silent-failure pattern."
    )
    # And just to be explicit: the body must not be a PVSetResponse with
    # success=False masquerading as a 200.
    if r.status_code == 200:
        body = r.json()
        assert body.get("success") is True, (
            "200 OK with success=False is the audited silent-failure pattern."
        )


@pytest.mark.asyncio
async def test_s2_set_pv_controller_raises_control_error_on_put_false():
    """Direct unit test: when ``_execute_put`` returns False, ``set_pv`` raises.

    Bypasses HTTP so the contract on the controller method itself is
    pinned: it must NEVER return ``PVSetResponse(success=False, ...)``.
    Earlier, this exact shape was the bug — a failed write quietly
    returned a "result" envelope advertising the requested value.
    """
    from datetime import datetime
    from unittest.mock import AsyncMock

    from direct_control.config import Settings
    from direct_control.device_controller import DeviceController
    from direct_control.models import (
        ControlError,
        CoordinationStatus,
        DeviceLockStatus,
        PVSetRequest,
    )

    class _AvailableCoord:
        async def check_device_available(self, device_name: str) -> CoordinationStatus:
            return CoordinationStatus(
                device_available=True,
                locked_by=None,
                status=DeviceLockStatus.AVAILABLE,
                timestamp=datetime.now(),
            )

        async def is_service_available(self) -> bool:
            return True

        async def cleanup(self) -> None:
            return None

    class _StubRegistry:
        async def get_owning_device(self, pv_name: str):
            return None

    settings = Settings()
    controller = DeviceController(settings, _AvailableCoord(), _StubRegistry())  # type: ignore[arg-type]
    # Force the put to "fail" without touching EPICS at all.
    controller._execute_put = AsyncMock(return_value=False)  # type: ignore[method-assign]

    with pytest.raises(ControlError, match="Failed to set PV"):
        await controller.set_pv(PVSetRequest(pv_name="ANY:PV", value=1.0, wait=True))


@pytest.mark.asyncio
async def test_s2_set_pv_controller_propagates_inner_exceptions():
    """If ``_execute_put`` itself raises, ``set_pv`` must let it propagate.

    Pre-fix the inner ``except Exception`` swallowed everything and
    returned ``success=False``; this test pins down that any inner
    failure now surfaces.
    """
    from datetime import datetime
    from unittest.mock import AsyncMock

    from direct_control.config import Settings
    from direct_control.device_controller import DeviceController
    from direct_control.models import (
        CoordinationStatus,
        DeviceLockStatus,
        PVSetRequest,
    )

    class _AvailableCoord:
        async def check_device_available(self, device_name: str) -> CoordinationStatus:
            return CoordinationStatus(
                device_available=True,
                locked_by=None,
                status=DeviceLockStatus.AVAILABLE,
                timestamp=datetime.now(),
            )

        async def is_service_available(self) -> bool:
            return True

        async def cleanup(self) -> None:
            return None

    class _StubRegistry:
        async def get_owning_device(self, pv_name: str):
            return None

    settings = Settings()
    controller = DeviceController(settings, _AvailableCoord(), _StubRegistry())  # type: ignore[arg-type]
    controller._execute_put = AsyncMock(  # type: ignore[method-assign]
        side_effect=RuntimeError("simulated EPICS write blew up"),
    )

    with pytest.raises(RuntimeError, match="simulated EPICS write blew up"):
        await controller.set_pv(PVSetRequest(pv_name="ANY:PV", value=1.0, wait=True))


# ─── S1: WebSocket path delivers error envelope (was stop_complete success=False) ──


def test_s1_ws_pv_socket_stop_emits_error_envelope(client):
    """``{action: stop}`` on the PV-socket must produce an error envelope.

    Pre-fix the WS handler called ``execute_device_method``, got back a
    placeholder ``DeviceCommandResponse(success=False, ...)`` and emitted
    a ``stop_complete`` event with ``success=False``. A WS client that
    only watched for ``type=="error"`` would miss the failure entirely.
    After the fix, ``execute_device_method`` raises and the WS handler
    routes the exception into ``send_error``.
    """
    import time

    with client.websocket_connect("/api/v1/pv-socket") as ws:
        ws.send_json({"action": "stop", "device": "some_device"})

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            msg = ws.receive_json()
            if msg.get("type") == "error":
                # The error envelope must mention the unimplemented
                # status — otherwise a future regression that swallows
                # the NotImplementedError silently would still pass.
                message = (msg.get("message") or "").lower()
                assert "not yet implemented" in message, (
                    f"error envelope missing not-implemented message: {msg!r}"
                )
                return
            # Defensive: the old bug would have produced this event.
            if msg.get("type") == "stop_complete" and msg.get("success") is False:
                pytest.fail(
                    f"received stop_complete with success=False — "
                    f"the silent-failure pattern is back: {msg!r}"
                )

        pytest.fail("never received an error envelope on /stop unimplemented")
