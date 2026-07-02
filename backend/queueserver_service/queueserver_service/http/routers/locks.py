import logging

import pydantic
from fastapi import APIRouter, Depends, Security
from packaging import version

if version.parse(pydantic.__version__) < version.parse("2.0.0"):
    from pydantic import BaseSettings
else:
    from pydantic_settings import BaseSettings

from ..authentication import get_current_principal
from ..re_manager_schemas import (
    LockResponse,
)
from ..resources import SERVER_RESOURCES as SR
from ..settings import get_settings
from ..utils import (
    get_api_access_manager,
    get_current_username,
    process_exception,
)

logger = logging.getLogger(__name__)

locks_router = APIRouter(prefix="/api")


@locks_router.post(
    "/lock",
    response_model=LockResponse,
    response_model_exclude_unset=True,
    summary="Acquire the manager lock",
    description=(
        "Acquire an exclusive lock on RE Manager, preventing other users from altering "
        "locked resources. Parameters: `lock_key` (str, required to unlock later), `note` "
        "(str, description shown to other users), `scope` (list of `'environment'` and/or "
        "`'queue'`). Required scope: `write:lock`."
    ),
    tags=["Lock"],
)
async def lock_handler(
    payload: dict,
    principal=Security(get_current_principal, scopes=["write:lock"]),
    settings: BaseSettings = Depends(get_settings),
    api_access_manager=Depends(get_api_access_manager),
):
    """
    Lock RE Manager.
    """
    try:
        username = get_current_username(
            principal=principal, settings=settings, api_access_manager=api_access_manager
        )[0]
        displayed_name = api_access_manager.get_displayed_user_name(username)
        payload.update({"user": displayed_name})

        msg = await SR.RM.lock(**payload)
    except Exception:
        process_exception()
    return msg


@locks_router.post(
    "/unlock",
    response_model=LockResponse,
    response_model_exclude_unset=True,
    summary="Release the manager lock",
    description=(
        "Release a previously-acquired manager lock. Parameter: `lock_key` (must match the "
        "value used at lock time). Required scope: `write:lock`."
    ),
    tags=["Lock"],
)
async def unlock_handler(
    payload: dict,
    principal=Security(get_current_principal, scopes=["write:lock"]),
):
    """
    Unlock RE Manager.
    """
    try:
        msg = await SR.RM.unlock(**payload)
    except Exception:
        process_exception()
    return msg


@locks_router.get(
    "/lock/info",
    response_model=LockResponse,
    response_model_exclude_unset=True,
    summary="Get current manager lock state",
    description=(
        "Returns the current lock state: who holds the lock, when it was acquired, the "
        "associated note, and which scopes are locked. "
        "Required scope: `read:lock`."
    ),
    tags=["Lock"],
)
async def lock_info_handler(
    payload: dict,
    principal=Security(get_current_principal, scopes=["read:lock"]),
):
    """
    Get current manager lock state.
    """
    try:
        msg = await SR.RM.lock_info(**payload)
    except Exception:
        process_exception()
    return msg
