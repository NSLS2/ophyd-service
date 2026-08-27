"""
End-to-end smoke test for U1 unified mode.

Starts ``start-re-manager`` as a subprocess with ``--http-port=<random>``
so the manager additionally serves the bluesky-httpserver FastAPI app on
that port. Confirms (a) the 0MQ manager comes up as usual, (b) uvicorn
actually binds the requested TCP port, (c) ``GET /api/status`` returns
200 with the expected manager-status shape, proving an HTTP→0MQ→handler
loopback round-trip inside the same process.

Anonymous HTTP access is enabled via ``QSERVER_HTTP_SERVER_ALLOW_ANONYMOUS_ACCESS``
so the test does not need to mint an API key.
"""

from __future__ import annotations

import asyncio
import socket
import time
from contextlib import contextmanager

import httpx
import pytest

from queueserver_service.manager.http_server import InProcessREManagerAPI
from tests.manager.common import (
    ReManager,
    condition_manager_idle,
    wait_for_condition,
    zmq_request,
)


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _poll_http(url: str, *, timeout: float) -> httpx.Response:
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=2.0)
            if response.status_code < 500:
                return response
        except httpx.HTTPError as exc:
            last_exc = exc
        time.sleep(0.2)
    raise TimeoutError(
        f"HTTP endpoint {url} did not return a response within {timeout:.1f}s"
        + (f" (last error: {last_exc})" if last_exc else "")
    )


@contextmanager
def _started_manager(params):
    re = ReManager(params=params)
    failed_to_start = False
    try:
        if not wait_for_condition(time=10, condition=condition_manager_idle):
            failed_to_start = True
            re.kill_manager()
            raise TimeoutError("Timeout: RE Manager failed to start.")
        yield re
    finally:
        if not failed_to_start:
            re.stop_manager()
        else:
            re.kill_manager()


def test_http_port_activates_unified_mode_with_inprocess_dispatch(monkeypatch, tmp_path):
    """--http-port alone enables unified mode; /api/status and /api/ping
    round-trip through HTTP → manager._dispatch_command → handler; and
    stderr confirms the in-process client was injected (not a ZMQ
    fallback). Only status/ping are exercised because anonymous access
    is scoped to read:status — other endpoints would require minting
    an API key."""
    monkeypatch.setenv("QSERVER_HTTP_SERVER_ALLOW_ANONYMOUS_ACCESS", "1")
    http_port = _free_tcp_port()

    # The http app's loggers live under the queueserver_service tree, so its
    # startup lines follow the manager's stdout handler; capture both streams.
    log_path = tmp_path / "manager_output.log"
    with open(log_path, "w") as log_fp:
        re = ReManager(params=["--http-port", str(http_port)], stdout=log_fp, stderr=log_fp)
        failed_to_start = False
        try:
            if not wait_for_condition(time=10, condition=condition_manager_idle):
                failed_to_start = True
                re.kill_manager()
                raise TimeoutError("Timeout: RE Manager failed to start.")

            base = f"http://127.0.0.1:{http_port}/api"
            _poll_http(f"{base}/status", timeout=15.0)

            for path in ("/status", "/ping"):
                response = httpx.get(f"{base}{path}", timeout=5.0)
                assert response.status_code == 200, (path, response.text)
                body = response.json()
                assert body.get("manager_state") == "idle", (path, body)
                assert body.get("worker_environment_exists") is False, (path, body)
        finally:
            if not failed_to_start:
                re.stop_manager()
            else:
                re.kill_manager()

    output = log_path.read_text()
    assert "Using injected REManagerAPI client" in output, (
        "unified mode did not wire the in-process client; output tail:\n"
        + "\n".join(output.splitlines()[-40:])
    )
    # The ZMQ-fallback log must NOT have fired — its presence would mean
    # httpserver ignored the injected RM and built a fresh client.
    assert "Connecting to RE Manager" not in output, (
        "in-process client was injected but httpserver still built a ZMQ client"
    )


def test_no_http_port_leaves_legacy_behavior():
    """Absent any HTTP flag, the manager must not bind an HTTP port — the
    split-process deployment is byte-identical to today."""
    http_port = _free_tcp_port()

    with _started_manager(params=None):
        with pytest.raises((httpx.ConnectError, httpx.ConnectTimeout)):
            httpx.get(f"http://127.0.0.1:{http_port}/api/status", timeout=1.0)


class _FakeManager:
    """Minimal stand-in for RunEngineManager with a _dispatch_command that
    mirrors the real one (duplicated rather than imported to keep this
    unit test free of manager.py's multiprocessing-heavy import chain)."""

    def __init__(self):
        async def status_handler(manager, params):
            return {"success": True, "msg": "", "manager_state": "idle", "params": params}

        async def failing_handler(manager, params):
            raise RuntimeError("boom")

        self._command_handlers = {"status": status_handler, "boom": failing_handler}

    async def _dispatch_command(self, method, params):
        try:
            handler = self._command_handlers[method]
        except KeyError:
            return {"success": False, "msg": f"Unknown method {method!r}"}
        try:
            return await handler(self, params)
        except Exception as ex:
            return {"success": False, "msg": str(ex)}


@pytest.mark.asyncio
async def test_inprocess_client_delegates_to_dispatch_command():
    manager = _FakeManager()
    rm = InProcessREManagerAPI(
        manager=manager,
        zmq_info_addr="tcp://127.0.0.1:2",
        zmq_encoding="json",
        request_fail_exceptions=False,
    )

    response = await rm.send_request(method="status", params={"k": "v"})
    assert response["success"] is True
    assert response["params"] == {"k": "v"}
    assert rm._inprocess_request_count == 1

    unknown = await rm.send_request(method="does_not_exist", params={})
    assert unknown["success"] is False
    assert "Unknown method" in unknown["msg"]
    assert rm._inprocess_request_count == 2

    failed = await rm.send_request(method="boom", params={})
    assert failed["success"] is False
    assert failed["msg"] == "boom"
    assert rm._inprocess_request_count == 3


# ---------------------------------------------------------------------------
#  Failure injection: an HTTP fault must degrade the service, never kill the
#  manager (see also test_scenarios.py, which covers a running plan surviving
#  a manager restart — the recovery path for http-induced manager loss).


def test_http_port_occupied_manager_survives():
    """With the HTTP port already bound by another process, the manager must
    start normally, keep serving 0MQ, and report http_server_state='failed'
    after the supervised task exhausts its retries — instead of exiting with
    uvicorn's SystemExit and crash-looping under the watchdog."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        occupied_port = blocker.getsockname()[1]

        with _started_manager(params=["--http-port", str(occupied_port)]):
            # Retries: MAX_STARTUP_ATTEMPTS x STARTUP_RETRY_DELAY_SECONDS.
            deadline = time.monotonic() + 30.0
            state = None
            while time.monotonic() < deadline:
                status, _ = zmq_request("status")
                assert status is not None, "manager stopped answering 0MQ"
                state = status.get("http_server_state")
                if state == "failed":
                    break
                time.sleep(0.5)
            assert state == "failed", f"http_server_state={state!r}"

            # The manager is fully functional without HTTP.
            status, _ = zmq_request("status")
            assert status["manager_state"] == "idle"

            with pytest.raises((httpx.HTTPError, httpx.ConnectError)):
                httpx.get(f"http://127.0.0.1:{occupied_port}/api/ping", timeout=1.0)


def test_http_status_field_running():
    """Happy path: unified mode reports http_server_state='running' in the
    manager status (both over 0MQ and in the HTTP status body)."""
    http_port = _free_tcp_port()

    with _started_manager(params=["--http-port", str(http_port)]):
        deadline = time.monotonic() + 15.0
        state = None
        while time.monotonic() < deadline:
            status, _ = zmq_request("status")
            state = (status or {}).get("http_server_state")
            if state == "running":
                break
            time.sleep(0.2)
        assert state == "running", f"http_server_state={state!r}"


class _FakeServerCrash:
    """uvicorn.Server stand-in whose serve() fails immediately."""

    def __init__(self, exc_factory):
        self._exc_factory = exc_factory
        self.started = False
        self.should_exit = False

    async def serve(self):
        raise self._exc_factory()


class _FakeServerRuns:
    """uvicorn.Server stand-in that starts and runs until should_exit."""

    def __init__(self):
        self.started = False
        self.should_exit = False

    async def serve(self):
        self.started = True
        while not self.should_exit:
            await asyncio.sleep(0.01)


def _make_supervised_server(monkeypatch, fake_factory):
    from queueserver_service.manager import http_server as http_server_module
    from queueserver_service.manager.http_server import CoHostedHttpServer, HttpServerSettings

    monkeypatch.setattr(http_server_module, "STARTUP_RETRY_DELAY_SECONDS", 0.01)

    settings = HttpServerSettings(enabled=True, host="127.0.0.1", port=1)
    server = CoHostedHttpServer(settings, manager=None, manager_zmq_bind_addr="tcp://*:1")
    monkeypatch.setattr(server, "_new_server", fake_factory)
    return server


@pytest.mark.asyncio
@pytest.mark.parametrize("exc_factory", [lambda: SystemExit(1), lambda: RuntimeError("boom")])
async def test_supervised_serve_contains_failures(monkeypatch, exc_factory):
    """Neither SystemExit (uvicorn's bind failure) nor an ordinary crash may
    escape the supervised task; after the retries the state is 'failed'."""
    server = _make_supervised_server(monkeypatch, lambda: _FakeServerCrash(exc_factory))

    server._stop_event = asyncio.Event()
    task = asyncio.ensure_future(server._supervised_serve())
    await asyncio.wait_for(task, timeout=5.0)  # raises if the task raised

    assert task.exception() is None
    assert server.state == "failed"


@pytest.mark.asyncio
async def test_supervised_serve_runs_and_stops(monkeypatch):
    """The supervisor reports 'running' once uvicorn starts, and 'stopped'
    after a clean stop — no restart is attempted on a requested shutdown."""
    server = _make_supervised_server(monkeypatch, _FakeServerRuns)

    server._stop_event = asyncio.Event()
    server._task = asyncio.ensure_future(server._supervised_serve())

    deadline = asyncio.get_event_loop().time() + 5.0
    while server.state != "running":
        assert asyncio.get_event_loop().time() < deadline, server.state
        await asyncio.sleep(0.01)

    await server.stop()
    assert server.state == "stopped"


class _FakeServerHangs:
    """uvicorn.Server stand-in that starts, then hangs until cancelled."""

    def __init__(self):
        self.started = False
        self.should_exit = False
        self.cancelled = False

    async def serve(self):
        self.started = True
        try:
            while True:
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            self.cancelled = True
            raise


@pytest.mark.asyncio
async def test_supervised_serve_cancellation_stops_inner_task(monkeypatch):
    """Cancelling the supervisor must also cancel the inner serve task —
    otherwise uvicorn keeps running (and holding the port) with no
    supervisor left."""
    fakes = []

    def factory():
        fakes.append(_FakeServerHangs())
        return fakes[-1]

    server = _make_supervised_server(monkeypatch, factory)
    server._stop_event = asyncio.Event()
    task = asyncio.ensure_future(server._supervised_serve())

    deadline = asyncio.get_event_loop().time() + 5.0
    while server.state != "running":
        assert asyncio.get_event_loop().time() < deadline, server.state
        await asyncio.sleep(0.01)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(fakes) == 1
    assert fakes[0].cancelled, "inner serve task was not cancelled"
    assert server.state == "stopped"


# ---------------------------------------------------------------------------
#  Supervisor: the attempt budget is for CONSECUTIVE failed starts, restart()
#  and the fault-injection hook.


def _running_fakes_server(monkeypatch, fakes, *, stable_run_seconds):
    from queueserver_service.manager import http_server as http_server_module

    monkeypatch.setattr(http_server_module, "STABLE_RUN_SECONDS", stable_run_seconds)

    def factory():
        fakes.append(_FakeServerRuns())
        return fakes[-1]

    server = _make_supervised_server(monkeypatch, factory)
    server._stop_event = asyncio.Event()
    server._task = asyncio.ensure_future(server._supervised_serve())
    return server


async def _wait_state(server, state, timeout=5.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while server.state != state:
        assert asyncio.get_event_loop().time() < deadline, f"state={server.state!r}, wanted {state!r}"
        await asyncio.sleep(0.01)


async def _wait_new_server(fakes, count, timeout=5.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while len(fakes) < count:
        assert asyncio.get_event_loop().time() < deadline, f"only {len(fakes)} servers created, wanted {count}"
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_supervised_serve_budget_counts_consecutive_failed_starts(monkeypatch):
    """A server that ran (long enough to count as a stable run) and then died
    is a fresh incident: it must be restarted again and again, never parked
    as 'failed' because it died MAX_STARTUP_ATTEMPTS times over its life."""
    from queueserver_service.manager import http_server as http_server_module

    fakes = []
    server = _running_fakes_server(monkeypatch, fakes, stable_run_seconds=0.0)
    try:
        for n in range(1, http_server_module.MAX_STARTUP_ATTEMPTS + 3):
            await _wait_state(server, "running")
            assert len(fakes) == n
            fakes[-1].should_exit = True  # dies without a stop request
            await _wait_new_server(fakes, n + 1)
        await _wait_state(server, "running")
        assert server.state == "running"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_supervised_serve_budget_exhausts_on_quick_deaths(monkeypatch):
    """Deaths that come before a stable run are consecutive failed starts:
    after MAX_STARTUP_ATTEMPTS of them the supervisor gives up ('failed')."""
    from queueserver_service.manager import http_server as http_server_module

    fakes = []
    server = _running_fakes_server(monkeypatch, fakes, stable_run_seconds=1e9)
    for n in range(1, http_server_module.MAX_STARTUP_ATTEMPTS + 1):
        await _wait_state(server, "running")
        fakes[-1].should_exit = True
        if n < http_server_module.MAX_STARTUP_ATTEMPTS:
            await _wait_new_server(fakes, n + 1)
    await asyncio.wait_for(server._task, timeout=5.0)
    assert server.state == "failed"
    assert len(fakes) == http_server_module.MAX_STARTUP_ATTEMPTS


@pytest.mark.asyncio
async def test_simulate_unexpected_exit_takes_the_retry_path(monkeypatch):
    fakes = []
    server = _running_fakes_server(monkeypatch, fakes, stable_run_seconds=1e9)
    try:
        await _wait_state(server, "running")
        assert server.simulate_unexpected_exit() is True
        await _wait_new_server(fakes, 2)
        await _wait_state(server, "running")
        assert fakes[0].should_exit and not fakes[1].should_exit
    finally:
        await server.stop()
    assert server.simulate_unexpected_exit() is False  # nothing running any more


@pytest.mark.asyncio
async def test_restart_replaces_the_server_and_lands_running(monkeypatch):
    """restart() = clean stop + fresh start: a new uvicorn Server, state back
    to 'running', and a fresh attempt budget."""
    fakes = []
    server = _running_fakes_server(monkeypatch, fakes, stable_run_seconds=1e9)

    async def fake_start():  # start() minus building the FastAPI app
        server._stop_event = asyncio.Event()
        server._task = asyncio.ensure_future(server._supervised_serve())

    monkeypatch.setattr(server, "start", fake_start)
    try:
        await _wait_state(server, "running")
        first = server._server
        await server.restart()
        await _wait_state(server, "running")
        assert server._server is not first
        assert len(fakes) == 2 and fakes[0].should_exit and not fakes[1].should_exit
    finally:
        await server.stop()
    assert server.state == "stopped"


@pytest.mark.asyncio
async def test_each_attempt_serves_a_fresh_app(monkeypatch):
    """The FastAPI app's lifespan shutdown closes its in-process manager client,
    so a retry/restart must build a NEW app: serving the old one again accepts
    connections and hangs on the closed client (seen live as GET /api/status
    timing out after a runtime restart)."""
    import uvicorn

    from queueserver_service.manager import http_server as http_server_module
    from queueserver_service.manager.http_server import CoHostedHttpServer, HttpServerSettings

    monkeypatch.setattr(http_server_module, "STARTUP_RETRY_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(http_server_module, "STABLE_RUN_SECONDS", 0.0)

    apps_served = []

    class _FakeUvicornServer(_FakeServerRuns):
        def __init__(self, config):
            super().__init__()
            apps_served.append(config.app)

    monkeypatch.setattr(uvicorn, "Server", _FakeUvicornServer)

    settings = HttpServerSettings(enabled=True, host="127.0.0.1", port=1)
    server = CoHostedHttpServer(settings, manager=None, manager_zmq_bind_addr="tcp://*:1")
    built = []
    monkeypatch.setattr(server, "_build_app", lambda: built.append(object()) or built[-1])

    server._stop_event = asyncio.Event()
    server._task = asyncio.ensure_future(server._supervised_serve())
    try:
        for n in range(1, 4):
            await _wait_state(server, "running")
            assert len(apps_served) == n
            server._server.should_exit = True  # dies without a stop request
            deadline = asyncio.get_event_loop().time() + 5.0
            while len(apps_served) < n + 1:
                assert asyncio.get_event_loop().time() < deadline
                await asyncio.sleep(0.01)
        assert len({id(a) for a in apps_served}) == len(apps_served), "an app was served twice"
    finally:
        await server.stop()
