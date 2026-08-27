import asyncio
import logging

from fastapi import APIRouter, Security

from ..authentication import get_current_principal
from ..re_manager_schemas import (
    SuccessMsgResponse,
)
from ..resources import SERVER_RESOURCES as SR
from ..utils import (
    process_exception,
)

logger = logging.getLogger(__name__)

admin_router = APIRouter(prefix="/api")


@admin_router.post(
    "/manager/stop",
    response_model=SuccessMsgResponse,
    response_model_exclude_unset=True,
    summary="Stop the RE Manager",
    description=(
        "Stop RE Manager. Unlike crash-and-restart behaviour, the manager will NOT be "
        "auto-restarted by the watchdog after a stop issued via this endpoint. "
        "Required scope: `write:manager:stop`."
    ),
    tags=["Manager"],
)
async def manager_stop_handler(
    payload: dict = {}, principal=Security(get_current_principal, scopes=["write:manager:stop"])
):
    """
    Stops of RE Manager. RE Manager will not be restarted after it is stoped.
    """
    try:
        msg = await SR.RM.send_request(method="manager_stop", params=payload)
    except Exception:
        process_exception()
    return msg


@admin_router.post(
    "/http_server/restart",
    response_model=SuccessMsgResponse,
    response_model_exclude_unset=True,
    summary="Restart the co-hosted HTTP server (unified mode)",
    description=(
        "Stop and start the HTTP server that is co-hosted in the RE Manager process, "
        "leaving the manager, the worker and any running plan untouched — the unified-mode "
        "equivalent of restarting a standalone httpserver service. The restart is scheduled "
        "after this response is sent, so the connection then drops and the server comes back "
        "a few seconds later. Fails when the manager runs in split-process mode. "
        "Required scope: `write:manager:control`."
    ),
    tags=["Admin"],
)
async def http_server_restart_handler(
    principal=Security(get_current_principal, scopes=["write:manager:control"]),
):
    """
    Restart the co-hosted HTTP server without affecting the RE Manager process, the RE Worker
    or a running plan.
    """
    try:
        msg = await SR.RM.send_request(method="http_server_restart")
    except Exception:
        process_exception()
    return msg


@admin_router.post(
    "/test/manager/kill",
    response_model=SuccessMsgResponse,
    response_model_exclude_unset=True,
    summary="Kill the manager event loop (testing only)",
    description=(
        "Halt the manager event loop to test client-side timeout handling and watchdog "
        "restart behaviour. Not for production use. "
        "Required scope: `write:testing`."
    ),
    tags=["Testing"],
)
async def test_manager_kill_handler(principal=Security(get_current_principal, scopes=["write:testing"])):
    """
    The command stops event loop of RE Manager process. Used for testing of RE Manager
    stability and handling of communication timeouts.
    """
    try:
        msg = await SR.RM.send_request(method="manager_kill")
    except Exception:
        process_exception()
    return msg


@admin_router.get(
    "/test/server/sleep",
    response_model=SuccessMsgResponse,
    response_model_exclude_unset=True,
    summary="Sleep on the server (testing only)",
    description=(
        "Sleep for `time` seconds then return success. Does not block the event loop or "
        "manager calls. Used to exercise client timeout handling. "
        "Required scope: `read:testing`."
    ),
    tags=["Testing"],
)
async def test_server_sleep_handler(
    payload: dict, principal=Security(get_current_principal, scopes=["read:testing"])
):
    """
    The API is intended for testing how the client applications and API libraries handle timeouts.
    The handler waits for the requested number of seconds and then returns the message indicating success.
    The API call is safe, since it does not block the event loop or calls to RE Manager
    """
    try:
        if "time" not in payload:
            raise IndexError(f"The required parameter 'time' is missing in the API call: {payload}")
        sleep_time = payload["time"]
        await asyncio.sleep(sleep_time)
        msg = {"success": True, "msg": ""}
    except Exception:
        process_exception()
    return msg
