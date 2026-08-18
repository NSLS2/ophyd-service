"""
Co-hosted HTTP server support for the RE Manager process (U1 unified mode).

When enabled, the manager schedules ``uvicorn.Server(...).serve()`` as a
background asyncio task alongside its 0MQ server. The bluesky-httpserver
FastAPI app is built via ``queueserver_service.http.app.build_app`` — unchanged
from the split-process deployment. Its internal REManagerAPI client (the
in-tree ``queueserver_service.http.manager_client`` port) still speaks 0MQ;
in unified mode it just loopbacks to the same process. Phase U2 will replace
the loopback with direct in-process handler calls.

Nothing at module scope pulls in ``uvicorn`` or ``queueserver_service.http``; the
legacy (HTTP-disabled) path never imports them.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 60610
SHUTDOWN_TIMEOUT_SECONDS = 10.0
# Supervision policy: a serve() failure (port already bound, crash in the
# ASGI stack) is retried a few times, then the server gives up and the
# manager continues 0MQ-only. The manager process must never die for it.
STARTUP_RETRY_DELAY_SECONDS = 2.0
MAX_STARTUP_ATTEMPTS = 3


@dataclasses.dataclass(frozen=True)
class HttpServerSettings:
    """Parsed ``http_server`` section of the manager configuration."""

    enabled: bool = False
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    config_path: Optional[str] = None

    @classmethod
    def from_config_dict(cls, section: Optional[Dict[str, Any]]) -> "HttpServerSettings":
        if not section:
            return cls()
        enabled = bool(section.get("enabled", False))
        if not enabled:
            return cls(enabled=False)
        host = section.get("host") or DEFAULT_HOST
        port = int(section.get("port") or DEFAULT_PORT)
        if not (1 <= port <= 65535):
            raise ValueError(f"http_server.port must be in [1, 65535] (got {port!r})")
        config_path = section.get("config_path") or None
        return cls(enabled=True, host=host, port=port, config_path=config_path)


def _bind_addr_to_connect_addr(bind_addr: str) -> str:
    """Turn a 0MQ bind address (``tcp://*:60615``) into a loopback connect
    address (``tcp://127.0.0.1:60615``) the FastAPI REManagerAPI client can
    use to reach the same process. Non-TCP addresses pass through."""
    match = re.fullmatch(r"tcp://([^:]+):(\d+)", bind_addr)
    if not match:
        return bind_addr
    host = match.group(1)
    if host in ("*", "0.0.0.0"):
        host = "127.0.0.1"
    return f"tcp://{host}:{match.group(2)}"


_in_process_rm_class: Any = None


def _build_in_process_rm_class():
    """Build the REManagerAPI subclass that short-circuits 0MQ CONTROL.

    Lazy: defers the ``queueserver_service.http.manager_client`` import
    until unified mode actually starts, keeping the HTTP stack off the
    legacy-path import graph.
    Overriding ``send_request`` catches all ~56 public methods (they all
    funnel through that one seam); overriding ``_create_client`` stubs
    out the otherwise-unused 0MQ CONTROL REQ socket so we don't hold a
    file descriptor and a zmq context to ourselves.
    """
    from queueserver_service.http.manager_client import REManagerAPI

    class _StubZMQClient:
        # send_message is never called on the in-process path; only close()
        # is invoked, by REManagerAPI.close() in the shutdown handler.
        def close(self):
            pass

    class _InProcessRM(REManagerAPI):
        def __init__(self, *, manager, **rm_kwargs):
            super().__init__(**rm_kwargs)
            self._manager = manager
            self._inprocess_request_count = 0

        def _create_client(self, **_):
            return _StubZMQClient()

        async def send_request(self, *, method, params=None):
            self._inprocess_request_count += 1
            response = await self._manager._dispatch_command(method, params or {})
            self._check_response(
                request={"method": method, "params": params},
                response=response,
            )
            return response

    return _InProcessRM


def InProcessREManagerAPI(*, manager, **rm_kwargs):
    """Construct the in-process REManagerAPI subclass (cached across calls)."""
    global _in_process_rm_class
    if _in_process_rm_class is None:
        _in_process_rm_class = _build_in_process_rm_class()
    return _in_process_rm_class(manager=manager, **rm_kwargs)


class CoHostedHttpServer:
    """Owns the lifecycle of a uvicorn.Server co-running with the manager.

    Start with ``await start()`` after the manager's 0MQ socket is bound
    (so the in-app REManagerAPI client can connect); stop with
    ``await stop()`` before the 0MQ socket closes (so in-flight HTTP→0MQ
    round-trips drain cleanly).

    The serve task is SUPERVISED: uvicorn raises SystemExit when the port
    cannot be bound, and an unhandled exception anywhere in the ASGI stack
    would otherwise die silently in an unawaited task. Both are contained
    here — retried up to ``MAX_STARTUP_ATTEMPTS`` and then abandoned with
    ``state == "failed"`` — so an HTTP failure degrades the service to
    0MQ-only instead of killing (or crash-looping) the manager process.
    ``state`` is surfaced as ``http_server_state`` in the manager status.
    """

    def __init__(
        self,
        settings: HttpServerSettings,
        *,
        manager: Any,
        manager_zmq_bind_addr: str,
    ) -> None:
        if not settings.enabled:
            raise ValueError(
                "CoHostedHttpServer constructed with disabled settings — "
                "this is a caller bug; guard on settings.enabled"
            )
        self._settings = settings
        self._manager = manager
        self._manager_zmq_connect_addr = _bind_addr_to_connect_addr(manager_zmq_bind_addr)
        self._server: Any = None  # uvicorn.Server
        self._task: Optional[asyncio.Task] = None
        self._uvicorn_config: Any = None
        self._state = "starting"
        self._stop_event: Optional[asyncio.Event] = None

    @property
    def state(self) -> str:
        """One of ``starting`` / ``running`` / ``retrying`` / ``failed`` / ``stopped``."""
        return self._state

    def _set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        # The manager serves a CACHED status dict; refresh it so the new
        # http_server_state is visible without waiting for another event.
        manager = self._manager
        if manager is not None:
            with contextlib.suppress(Exception):
                manager._status_update()

    async def _serve_and_capture_exit(self) -> Optional[SystemExit]:
        # SystemExit raised inside an asyncio task propagates THROUGH the
        # event loop (Task.__step re-raises it), killing the whole process —
        # the exact uvicorn bind-failure path this supervisor exists to
        # contain. Convert it to a return value inside the task so it can
        # never reach the loop.
        try:
            await self._server.serve()
            return None
        except SystemExit as exc:
            return exc

    def _new_server(self) -> Any:
        import uvicorn

        server = uvicorn.Server(self._uvicorn_config)
        # The manager owns signal handling for its process. Left alone,
        # uvicorn installs its own SIGINT/SIGTERM handlers on the main
        # thread for the lifetime of serve() and re-raises captured
        # signals inside this (supervised) task — which would turn a
        # Ctrl-C into an HTTP-restart instead of a manager shutdown.
        server.capture_signals = contextlib.nullcontext
        return server

    async def _supervised_serve(self) -> None:
        stop_event = self._stop_event
        assert stop_event is not None  # set in start() before this task is created
        attempts = 0
        while True:
            attempts += 1
            try:
                self._set_state("starting")
                self._server = self._new_server()
                serve_task = asyncio.ensure_future(self._serve_and_capture_exit())
                while not serve_task.done() and not self._server.started:
                    await asyncio.sleep(0.05)
                if self._server.started:
                    self._set_state("running")
                    logger.info(
                        "Co-hosted HTTP server is running on %s:%d",
                        self._settings.host,
                        self._settings.port,
                    )
                exit_exc = await serve_task
                if exit_exc is not None:
                    # uvicorn calls sys.exit(1) when the port cannot be
                    # bound; left uncontained it would kill the manager and
                    # the watchdog would restart it into the same failure,
                    # forever.
                    logger.error(
                        "Co-hosted HTTP server failed (SystemExit code %s) — "
                        "typically the port %s:%d is unavailable; the manager continues",
                        exit_exc.code,
                        self._settings.host,
                        self._settings.port,
                    )
                elif stop_event.is_set():
                    self._set_state("stopped")
                    return
                else:
                    logger.error(
                        "Co-hosted HTTP server exited unexpectedly; the manager continues"
                    )
            except asyncio.CancelledError:
                self._set_state("stopped")
                raise
            except Exception:
                logger.exception("Co-hosted HTTP server crashed; the manager continues")

            if stop_event.is_set():
                self._set_state("stopped")
                return
            if attempts >= MAX_STARTUP_ATTEMPTS:
                self._set_state("failed")
                logger.error(
                    "Co-hosted HTTP server gave up after %d attempt(s); "
                    "continuing without HTTP (0MQ API remains available)",
                    attempts,
                )
                return
            self._set_state("retrying")
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop_event.wait(), STARTUP_RETRY_DELAY_SECONDS)

    async def start(self) -> None:
        import uvicorn
        from queueserver_service.http.app import build_app
        from queueserver_service.http.config import construct_build_app_kwargs, parse_configs

        if self._settings.config_path:
            hs_config = parse_configs(self._settings.config_path)
            build_kwargs = construct_build_app_kwargs(
                hs_config, source_filepath=self._settings.config_path
            )
        else:
            build_kwargs = construct_build_app_kwargs({})

        server_settings = build_kwargs.setdefault("server_settings", {})
        zmq_conf = server_settings.setdefault("qserver_zmq_configuration", {})
        zmq_conf.setdefault("control_address", self._manager_zmq_connect_addr)

        # In-process RM dispatches into manager._dispatch_command directly.
        # The 0MQ INFO/PUB channel is still configured so the parent class's
        # console / system-info monitors keep working; the CONTROL REQ
        # client is replaced by a no-op stub via _create_client override.
        server_settings["rm_client"] = InProcessREManagerAPI(
            manager=self._manager,
            zmq_info_addr=zmq_conf.get("info_address"),
            zmq_encoding=zmq_conf.get("encoding"),
            zmq_public_key=zmq_conf.get("public_key"),
            request_fail_exceptions=False,
            status_expiration_period=0.4,
            console_monitor_max_lines=2000,
        )

        app = build_app(**build_kwargs)

        self._uvicorn_config = uvicorn.Config(
            app,
            host=self._settings.host,
            port=self._settings.port,
            log_level="info",
            lifespan="on",
        )
        self._stop_event = asyncio.Event()
        self._task = asyncio.ensure_future(self._supervised_serve())
        logger.info(
            "Co-hosted HTTP server starting on %s:%d (manager 0MQ at %s)",
            self._settings.host,
            self._settings.port,
            self._manager_zmq_connect_addr,
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        if self._stop_event is not None:
            self._stop_event.set()
        if self._server is not None:
            self._server.should_exit = True
        try:
            await asyncio.wait_for(self._task, timeout=SHUTDOWN_TIMEOUT_SECONDS)
            logger.info("Co-hosted HTTP server stopped cleanly")
        except asyncio.TimeoutError:
            logger.warning(
                "Co-hosted HTTP server did not exit within %.1fs; cancelling",
                SHUTDOWN_TIMEOUT_SECONDS,
            )
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        finally:
            self._set_state("stopped")
            self._server = None
            self._task = None
