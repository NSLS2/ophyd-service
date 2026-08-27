"""
Process-level fault isolation for the unified queueserver.

Vocabulary used here (it is easy to blur):

* **watchdog** — the ``start-re-manager`` OS *process* itself (the one a
  ``systemctl`` unit manages). It never runs plans; it spawns the two below
  and restarts the manager when its heartbeat stops.
* **RE Manager** — a child OS *process* of the watchdog (``multiprocessing``).
  Owns the 0MQ control socket and, in unified mode, the HTTP server.
* **RE Worker** — a second child OS *process* of the watchdog, a *sibling* of
  the manager (not its child). Runs the RunEngine and the plans.
* **co-hosted HTTP server** — not a process and not a thread: an asyncio
  *task* on the manager's event loop (``CoHostedHttpServer``).

Each test faults exactly one of those and asserts, by PID, which of the
others kept running. The tests start ``start-re-manager`` as a real
subprocess and find the manager and worker as children of the watchdog via
``/proc`` (Linux only — the whole subprocess harness is).
"""

from __future__ import annotations

import os
import signal
import socket
import time
from contextlib import contextmanager

import httpx
import pytest

from queueserver_service.manager.qserver_cli import create_msg
from tests.manager.common import (  # noqa: F401
    ReManager,
    clear_redis_pool,
    condition_environment_created,
    condition_manager_idle,
    re_manager,
    re_manager_factory,
    wait_for_condition,
    zmq_request,
)

pytestmark = pytest.mark.skipif(not os.path.isdir("/proc"), reason="needs /proc to walk the process tree")


# ---------------------------------------------------------------- helpers


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _alive(pid: int) -> bool:
    """True if ``pid`` exists and is not a zombie."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        with open(f"/proc/{pid}/stat") as fh:
            state = fh.read().rpartition(")")[2].split()[0]
    except FileNotFoundError:
        return False
    return state != "Z"


def _cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return fh.read().replace(b"\0", b" ").decode(errors="replace")
    except FileNotFoundError:
        return ""


def _children(pid: int) -> list[int]:
    """Live, non-helper child processes of ``pid`` (multiprocessing's
    resource tracker, if any, is not one of ours).

    ``/proc/<pid>/task/<tid>/children`` is per THREAD: the watchdog forks the
    manager from its main thread but the worker from its pipe-RPC thread, so
    every task directory has to be read."""
    pids: set[int] = set()
    try:
        tids = os.listdir(f"/proc/{pid}/task")
    except FileNotFoundError:
        return []
    for tid in tids:
        try:
            with open(f"/proc/{pid}/task/{tid}/children") as fh:
                pids.update(int(x) for x in fh.read().split())
        except FileNotFoundError:
            continue
    return sorted(p for p in pids if _alive(p) and "resource_tracker" not in _cmdline(p))


def _wait_until(predicate, *, timeout: float, period: float = 0.2, what: str = "condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(period)
    raise TimeoutError(f"{what} not met within {timeout:.0f}s")


def _status() -> dict:
    status, err = zmq_request("status")
    assert status is not None, f"manager stopped answering 0MQ: {err}"
    return status


def _http_state() -> str | None:
    status, _ = zmq_request("status")
    return (status or {}).get("http_server_state")


def _wait_http_running(timeout: float = 20.0) -> None:
    _wait_until(lambda: _http_state() == "running", timeout=timeout, what="http_server_state == running")


def _http_get_status(port: int) -> httpx.Response:
    return httpx.get(f"http://127.0.0.1:{port}/api/status", timeout=2.0)


class _Tree:
    """PIDs of the start-re-manager process tree, re-discoverable after faults."""

    def __init__(self, re: ReManager):
        self.re = re
        self.watchdog: int = re._p.pid
        self.manager: int | None = None
        self.worker: int | None = None

    def discover_manager(self) -> int:
        kids = _children(self.watchdog)
        kids = [p for p in kids if p != self.worker]
        assert len(kids) == 1, f"expected exactly one manager child of the watchdog, saw {kids}"
        self.manager = kids[0]
        return self.manager

    def discover_worker(self) -> int:
        kids = [p for p in _children(self.watchdog) if p != self.manager]
        assert len(kids) == 1, f"expected exactly one worker child of the watchdog, saw {kids}"
        self.worker = kids[0]
        return self.worker

    def open_environment(self) -> int:
        resp, _ = zmq_request("environment_open")
        assert resp and resp["success"], resp
        assert wait_for_condition(time=60, condition=condition_environment_created)
        return self.discover_worker()


class _ManagerLog:
    """The manager tree's combined stdout/stderr, for asserting on lifecycle
    log lines (the only external evidence of an HTTP restart that is not a
    millisecond-wide state transition)."""

    def __init__(self, path):
        self.path = path
        self._pos = 0

    def mark(self) -> None:
        """Forget everything logged so far."""
        self._pos = os.path.getsize(self.path)

    def since_mark(self) -> str:
        with open(self.path, errors="replace") as fh:
            fh.seek(self._pos)
            return fh.read()

    def wait_for(self, needle: str, *, timeout: float) -> None:
        _wait_until(lambda: needle in self.since_mark(), timeout=timeout, what=f"log line {needle!r}")


@contextmanager
def _unified_tree(monkeypatch, tmp_path, http_port: int):
    """start-re-manager --http-port <port>, environment opened, PIDs known."""
    monkeypatch.setenv("QSERVER_HTTP_SERVER_ALLOW_ANONYMOUS_ACCESS", "1")
    log_path = tmp_path / "manager.log"
    # The subprocess gets its own copy of the descriptor, so closing ours on
    # the way out (including when ReManager() itself raises) is safe.
    with open(log_path, "w") as log_file:
        re = ReManager(params=["--http-port", str(http_port)], stdout=log_file, stderr=log_file)
        tree = _Tree(re)
        tree.log = _ManagerLog(log_path)
        try:
            assert wait_for_condition(time=60, condition=condition_manager_idle), "RE Manager failed to start"
            tree.discover_manager()
            tree.open_environment()
            _wait_http_running()
            yield tree
        finally:
            # Whatever the test left behind: an orderly stop if the tree is
            # intact, otherwise kill the survivors ourselves.
            if re._p is not None and re._p.poll() is None:
                re.stop_manager()
            else:
                for pid in (tree.manager, tree.worker):
                    if pid and _alive(pid):
                        os.kill(pid, signal.SIGKILL)
                re._p = None
                clear_redis_pool()


# ---------------------------------------------------------------- tests


def test_manager_death_leaves_worker_and_watchdog_alive(monkeypatch, tmp_path):
    """Kill the RE Manager (manager_kill freezes its event loop; the watchdog
    SIGKILLs it after the heartbeat timeout and starts a new one). The worker
    and the watchdog keep their PIDs, the new manager re-attaches to the
    live worker, and the co-hosted HTTP server comes back in the new process."""
    http_port = _free_tcp_port()
    with _unified_tree(monkeypatch, tmp_path, http_port) as tree:
        watchdog, manager0, worker0 = tree.watchdog, tree.manager, tree.worker
        assert _http_get_status(http_port).status_code == 200

        zmq_request("manager_kill")  # no reply by design: the loop is frozen

        assert wait_for_condition(time=40, condition=condition_manager_idle), "watchdog did not restart the manager"
        assert not _alive(manager0), "the old manager process is still alive"
        manager1 = tree.discover_manager()
        assert manager1 != manager0

        assert _alive(watchdog) and tree.re._p.pid == watchdog
        assert _alive(worker0) and tree.discover_worker() == worker0, "the worker did not survive the manager restart"
        assert _status()["worker_environment_exists"] is True, "new manager did not re-attach to the live worker"

        _wait_http_running()
        assert _http_get_status(http_port).status_code == 200


def test_worker_death_leaves_manager_and_watchdog_alive(monkeypatch, tmp_path):
    """SIGKILL the RE Worker (as an OOM kill would). The manager and watchdog
    keep their PIDs, the manager notices (environment reported gone) and can
    open a fresh environment — a new worker process — while HTTP stays up."""
    http_port = _free_tcp_port()
    with _unified_tree(monkeypatch, tmp_path, http_port) as tree:
        watchdog, manager0, worker0 = tree.watchdog, tree.manager, tree.worker

        os.kill(worker0, signal.SIGKILL)

        _wait_until(
            lambda: _status()["worker_environment_exists"] is False,
            timeout=60,
            what="manager reporting the environment gone",
        )
        assert not _alive(worker0)
        assert _alive(manager0) and tree.discover_manager() == manager0, "the manager did not survive the worker's death"
        assert _alive(watchdog)
        assert _status()["manager_state"] == "idle"
        assert _http_state() == "running"
        assert _http_get_status(http_port).status_code == 200

        worker1 = tree.open_environment()
        assert worker1 != worker0 and _alive(worker1)
        assert tree.manager == manager0


def test_watchdog_death_leaves_manager_and_worker_serving(monkeypatch, tmp_path):
    """SIGKILL the watchdog — the start-re-manager process a service unit
    would manage. The manager (0MQ and HTTP) and the worker are orphaned but
    keep serving: nothing restarts them and nothing takes them down, for
    longer than the heartbeat timeout would have taken to act."""
    http_port = _free_tcp_port()
    with _unified_tree(monkeypatch, tmp_path, http_port) as tree:
        watchdog, manager0, worker0 = tree.watchdog, tree.manager, tree.worker

        os.kill(watchdog, signal.SIGKILL)
        tree.re._p.wait(timeout=10)  # reap it so it cannot be mistaken for alive

        deadline = time.monotonic() + 8.0  # > the 5 s heartbeat timeout
        while time.monotonic() < deadline:
            status = _status()
            assert status["manager_state"] == "idle"
            assert status["worker_environment_exists"] is True
            assert _alive(manager0), "manager died after losing the watchdog"
            assert _alive(worker0), "worker died after losing the watchdog"
            assert _http_get_status(http_port).status_code == 200
            time.sleep(1.0)


def test_http_task_exit_is_contained_and_restarted(monkeypatch, tmp_path):
    """Make the co-hosted HTTP server exit at runtime as if it had died. The
    supervisor logs it, restarts it (a fresh app that actually answers), and
    the manager and worker PIDs are unchanged with 0MQ answering throughout."""
    http_port = _free_tcp_port()
    with _unified_tree(monkeypatch, tmp_path, http_port) as tree:
        manager0, worker0 = tree.manager, tree.worker
        tree.log.mark()

        resp, _ = zmq_request("manager_test", params={"test_name": "http_server_exit"})
        assert resp and resp["success"], resp

        tree.log.wait_for("Co-hosted HTTP server exited unexpectedly; the manager continues", timeout=15)
        tree.log.wait_for("Co-hosted HTTP server is running on", timeout=20)
        _wait_http_running()
        assert _http_get_status(http_port).status_code == 200  # the restarted server really answers

        assert tree.discover_manager() == manager0 and _alive(manager0)
        assert tree.discover_worker() == worker0 and _alive(worker0)
        assert _status()["worker_environment_exists"] is True


def test_http_server_restart_command_bounces_only_http(monkeypatch, tmp_path):
    """``http_server_restart`` over 0MQ stops and restarts the HTTP server
    (clean stop, then a fresh start that answers); manager and worker PIDs
    are unchanged. Over HTTP the endpoint exists and is gated by a write
    scope (anonymous is read-only here)."""
    http_port = _free_tcp_port()
    with _unified_tree(monkeypatch, tmp_path, http_port) as tree:
        manager0, worker0 = tree.manager, tree.worker
        tree.log.mark()

        resp, _ = zmq_request("http_server_restart")
        assert resp and resp["success"], resp
        assert "scheduled" in resp["msg"]

        tree.log.wait_for("Co-hosted HTTP server stopped cleanly", timeout=20)
        tree.log.wait_for("Co-hosted HTTP server is running on", timeout=20)
        _wait_http_running()
        assert _http_get_status(http_port).status_code == 200

        assert tree.discover_manager() == manager0 and _alive(manager0)
        assert tree.discover_worker() == worker0 and _alive(worker0)

        gated = httpx.post(f"http://127.0.0.1:{http_port}/api/http_server/restart", timeout=5.0)
        assert gated.status_code in (401, 403), gated.text


def test_http_server_restart_refused_in_split_process_mode(re_manager):  # noqa: F811
    """Without --http-port there is no co-hosted server to restart; the
    command says so instead of pretending."""
    resp, _ = zmq_request("http_server_restart")
    assert resp and resp["success"] is False, resp
    assert "not enabled" in resp["msg"]


def test_cli_parses_http_server_restart():
    method, prms, _ = create_msg(["http-server", "restart"], lock_key=None)
    assert method == "http_server_restart"
    assert prms == {}
