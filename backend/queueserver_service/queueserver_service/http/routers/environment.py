import logging

from fastapi import APIRouter, Security

from ..authentication import get_current_principal
from ..re_manager_schemas import (
    SuccessMsgResponse,
    TaskUidResponse,
)
from ..resources import SERVER_RESOURCES as SR
from ..utils import (
    process_exception,
)

logger = logging.getLogger(__name__)

environment_router = APIRouter(prefix="/api")


@environment_router.post(
    "/environment/open",
    response_model=SuccessMsgResponse,
    response_model_exclude_unset=True,
    summary="Open the RE environment",
    description=(
        "Spawn the RE Worker subprocess and initialize the Run Engine. Required before the "
        "queue can execute plans or before scripts/functions can be uploaded. "
        "Required scope: `write:manager:control`."
    ),
    tags=["Environment"],
)
async def environment_open_handler(
    payload: dict = {}, principal=Security(get_current_principal, scopes=["write:manager:control"])
):
    """
    Creates RE environment: creates RE Worker process, starts and configures Run Engine.
    """
    try:
        msg = await SR.RM.environment_open(**payload)
    except Exception:
        process_exception()
    return msg


@environment_router.post(
    "/environment/close",
    response_model=SuccessMsgResponse,
    response_model_exclude_unset=True,
    summary="Close the RE environment cleanly",
    description=(
        "Orderly shutdown of the RE Worker. Rejected if a plan is currently running — call "
        "`/queue/stop` or `/re/stop` first, or use `/environment/destroy` for a forceful "
        "shutdown. Required scope: `write:manager:control`."
    ),
    tags=["Environment"],
)
async def environment_close_handler(
    payload: dict = {}, principal=Security(get_current_principal, scopes=["write:manager:control"])
):
    """
    Orderly closes of RE environment. The command returns success only if no plan is running,
    i.e. RE Manager is in the idle state. The command is rejected if a plan is running.
    """
    try:
        msg = await SR.RM.environment_close(**payload)
    except Exception:
        process_exception()
    return msg


@environment_router.post(
    "/environment/destroy",
    response_model=SuccessMsgResponse,
    response_model_exclude_unset=True,
    summary="Forcefully destroy the RE environment",
    description=(
        "Kill the RE Worker process without waiting for the running plan to complete. "
        "Last-resort recovery path — intended for expert operators when the worker is hung "
        "and cannot be stopped cleanly. Required scope: `write:manager:control`."
    ),
    tags=["Environment"],
)
async def environment_destroy_handler(
    payload: dict = {}, principal=Security(get_current_principal, scopes=["write:manager:control"])
):
    """
    Destroys RE environment by killing RE Worker process. This is a last resort command which
    should be made available only to expert level users.
    """
    try:
        msg = await SR.RM.environment_destroy(**payload)
    except Exception:
        process_exception()
    return msg


@environment_router.post(
    "/environment/update",
    response_model=TaskUidResponse,
    response_model_exclude_unset=True,
    summary="Refresh environment caches",
    description=(
        "Refresh manager-side caches of plans, devices, and namespace metadata from the "
        "running worker. Call after uploading a script that adds or redefines plans/devices "
        "so subsequent `/plans/*` and `/devices/*` responses reflect the change. "
        "Required scope: `write:queue:control`."
    ),
    tags=["Environment"],
)
async def environment_update_handler(
    payload: dict = {}, principal=Security(get_current_principal, scopes=["write:queue:control"])
):
    """
    Updates RE environment cache.
    """
    try:
        msg = await SR.RM.environment_update(**payload)
    except Exception:
        process_exception()
    return msg
