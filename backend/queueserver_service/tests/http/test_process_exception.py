"""Unit coverage for ``process_exception`` — the shared HTTP error mapper.

``process_exception`` is called from the ``except`` block of ~70 handlers across
every router; it re-raises the in-flight exception as an ``HTTPException``,
mapping RE Manager request timeouts to 408 and everything else to 400. Its
behavior is otherwise only exercised indirectly (custom-router fixtures and
flaky ZMQ-timeout integration tests), so pin the mapping directly here.
"""

import pytest
from bluesky_queueserver_api.zmq.aio import REManagerAPI
from fastapi import HTTPException

from queueserver_service.http.utils import process_exception


def test_request_timeout_maps_to_408():
    with pytest.raises(HTTPException) as excinfo:
        try:
            raise REManagerAPI.RequestTimeoutError(
                "manager did not respond", {"method": "status"}
            )
        except Exception:
            process_exception()
    assert excinfo.value.status_code == 408
    assert "manager did not respond" in excinfo.value.detail


def test_generic_exception_maps_to_400():
    with pytest.raises(HTTPException) as excinfo:
        try:
            raise RuntimeError("unexpected boom")
        except Exception:
            process_exception()
    assert excinfo.value.status_code == 400
    assert "unexpected boom" in excinfo.value.detail
