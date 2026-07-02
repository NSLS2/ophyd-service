import logging

from fastapi import APIRouter, Request, Security

from ..authentication import get_current_principal
from ..re_manager_schemas import (
    ConfigGetResponse,
    StatusResponse,
)
from ..resources import SERVER_RESOURCES as SR
from ..utils import (
    process_exception,
)

logger = logging.getLogger(__name__)

status_router = APIRouter(prefix="/api")


@status_router.get(
    "/",
    response_model=StatusResponse,
    response_model_exclude_unset=True,
    summary="Ping the RE Manager (root alias)",
    description=(
        "Returns a minimal response from RE Manager. Same handler as `/api/ping`. "
        "Useful as a basic reachability/liveness check. Required scope: `read:status`."
    ),
    tags=["Status"],
)
@status_router.get(
    "/ping",
    response_model=StatusResponse,
    response_model_exclude_unset=True,
    summary="Ping the RE Manager",
    description=(
        "Returns a minimal response from RE Manager — a lightweight way to confirm the "
        "server is reachable and the manager process is responsive. Required scope: `read:status`."
    ),
    tags=["Status"],
)
async def ping_handler(payload: dict = {}, principal=Security(get_current_principal, scopes=["read:status"])):
    """
    May be called to get some response from the server. Currently returns status of RE Manager.
    """
    try:
        msg = await SR.RM.ping(**payload)
    except Exception:
        process_exception()
    return msg


@status_router.get(
    "/status",
    response_model=StatusResponse,
    response_model_exclude_unset=True,
    summary="Get RE Manager status",
    description=(
        "Returns a status snapshot of RE Manager — manager state, environment state, the "
        "currently running item (if any), worker process status, queue/history counts, "
        "plus the UIDs clients use for change detection when polling. "
        "Required scope: `read:status`."
    ),
    tags=["Status"],
)
async def status_handler(
    request: Request,
    payload: dict = {},
    principal=Security(get_current_principal, scopes=["read:status"]),
):
    """
    Returns status of RE Manager.
    """
    request.state.endpoint = "status"
    # logger.info(f"payload = {payload} principal={principal}")
    try:
        msg = await SR.RM.status(**payload)
    except Exception:
        process_exception()
    return msg


@status_router.get(
    "/config/get",
    response_model=ConfigGetResponse,
    response_model_exclude_unset=True,
    summary="Get manager configuration",
    description=(
        "Returns the manager's client-visible configuration dictionary (the subset of "
        "settings considered safe to expose). Required scope: `read:config`."
    ),
    tags=["Config"],
)
async def queue_config_get(
    payload: dict = {},
    principal=Security(get_current_principal, scopes=["read:config"]),
):
    """
    Get manager configuration.
    """
    try:
        msg = await SR.RM.config_get(**payload)
    except Exception:
        process_exception()
    return msg
