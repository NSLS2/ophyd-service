"""
Finch WS envelope contract pins.

``finch/src/api/ophyd/ophyd{PV,Device}SocketTypes.ts`` is the source of
truth for the wire shapes our WS endpoints emit. These tests pin the
invariants not already covered by the silent-failure audit suite in
``test_silent_failure_resolutions.py`` — the two suites together cover
the full envelope surface.

Driven against the caproto test IOC (see ``tests/conftest.py::test_ioc``).
``IOC:counter`` emits an initial-value monitor on subscribe, which is
all these contract tests need.
"""

import time

import pytest


def test_pv_update_event_type_literal(client):
    """pv_update envelope's ``event_type`` must be the literal string ``"pv_update"``.

    Internal stable convention from ``PVUpdate.event_type`` default
    in ``direct_control/models.py``. finch ignores this field but
    SDK codegen and intermediaries rely on the literal value.
    """
    with client.websocket_connect("/api/v1/pv-socket") as ws:
        ws.send_json({"action": "subscribe", "pv": "IOC:counter"})

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            msg = ws.receive_json()
            if msg.get("pv") == "IOC:counter" and "event_type" in msg and msg.get("sub_type") is None:
                assert msg["event_type"] == "pv_update", (
                    f"event_type must literally be 'pv_update'; got {msg['event_type']!r}"
                )
                return

        pytest.fail("never received pv_update for IOC:counter")


def test_pv_update_carries_all_value_update_response_fields(client):
    """pv_update must include every key from finch's ``ValueUpdateResponse``.

    Source: ``finch/src/api/ophyd/ophydPVSocketTypes.ts`` (``ValueUpdateResponse``):
    pv, value, timestamp, connected, read_access, write_access.
    Missing any one of these is an undefined on the finch side.
    """
    required = {"pv", "value", "timestamp", "connected", "read_access", "write_access"}

    with client.websocket_connect("/api/v1/pv-socket") as ws:
        ws.send_json({"action": "subscribe", "pv": "IOC:counter"})

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            msg = ws.receive_json()
            if msg.get("event_type") == "pv_update" and msg.get("pv") == "IOC:counter":
                missing = required - set(msg)
                assert not missing, (
                    f"pv_update missing finch ValueUpdateResponse keys: {sorted(missing)}. "
                    f"Got keys: {sorted(msg)}"
                )
                return

        pytest.fail("never received pv_update for IOC:counter")


def test_device_update_event_type_and_device_field(client):
    """device_update envelope must carry ``event_type='device_update'`` + ``device`` field.

    Source: ``finch/src/api/ophyd/ophydDeviceSocketTypes.ts``
    (``ValueUpdateResponse``) discriminates on the ``device`` key, not
    ``device_name``. The ``event_type`` literal is our own stable
    convention from ``DeviceUpdate.event_type`` default.
    """
    from direct_control.models import DeviceInfo

    app = client.app
    device_ws_manager = app.state.device_ws_manager

    async def _stub_fetch(device_name: str):
        return (
            DeviceInfo(name=device_name, device_type="motor", pvs={"readback": "IOC:counter"}),
            None,
        )

    device_ws_manager._fetch_device_info = _stub_fetch  # type: ignore[method-assign]

    with client.websocket_connect("/api/v1/device-socket") as ws:
        ws.send_json({"action": "subscribe", "device": "fake_motor"})

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            msg = ws.receive_json()
            # Loose predicate so the inner asserts can pin the literals — a
            # regression like event_type='value' should surface as a specific
            # assertion message, not pytest.fail's "never received...".
            if msg.get("device") == "fake_motor" and "event_type" in msg and msg.get("sub_type") is None:
                assert msg["event_type"] == "device_update", (
                    f"event_type must literally be 'device_update'; got {msg['event_type']!r}"
                )
                assert "device_name" not in msg, (
                    f"device_update still carries legacy 'device_name' field: {msg!r}"
                )
                return

        pytest.fail("never received device_update for fake_motor")


def test_meta_envelope_carries_finch_required_keys(client):
    """Meta envelope must include every key from finch's ``MetaUpdateResponseBase`` we emit.

    Source: ``finch/src/api/ophyd/ophydPVSocketTypes.ts`` (``MetaUpdateResponseBase``):
    status, severity, precision, lower_ctrl_limit, upper_ctrl_limit,
    units, enum_strs, sub_type. The ``setpoint_*`` fields finch also
    declares are nullable on its side and intentionally not emitted by
    the backend today; that's a tracked follow-up.
    """
    required = {
        "sub_type",
        "status",
        "severity",
        "precision",
        "lower_ctrl_limit",
        "upper_ctrl_limit",
        "units",
        "enum_strs",
    }

    with client.websocket_connect("/api/v1/pv-socket") as ws:
        ws.send_json({"action": "subscribe", "pv": "IOC:counter"})

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            msg = ws.receive_json()
            if msg.get("sub_type") == "meta" and msg.get("pv") == "IOC:counter":
                missing = required - set(msg)
                assert not missing, (
                    f"meta envelope missing finch MetaUpdateResponseBase keys: "
                    f"{sorted(missing)}. Got keys: {sorted(msg)}"
                )
                return

        pytest.fail("never received sub_type:meta envelope on subscribe")


def test_error_envelope_full_shape(client):
    """Error envelope must carry ``type='error'``, ``timestamp``, and ``error`` (message text).

    Source: ``finch/src/api/ophyd/ophydPVSocketTypes.ts`` (``ErrorResponse``)
    declares only ``error: string``. The ``type`` and ``timestamp``
    fields come from ``send_event`` in ``_envelopes.py`` and are part
    of our wire schema even though finch doesn't read them.
    """
    with client.websocket_connect("/api/v1/pv-socket") as ws:
        ws.send_json({"action": "set"})  # missing pv + value → send_error

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            msg = ws.receive_json()
            if msg.get("type") == "error":
                assert "error" in msg and isinstance(msg["error"], str), (
                    f"error envelope missing string 'error' field: {msg!r}"
                )
                assert "timestamp" in msg, (
                    f"error envelope missing 'timestamp' field: {msg!r}"
                )
                return

        pytest.fail("never received error envelope for malformed set request")
