import logging

import pydantic
from queueserver_service.manager.conversions import simplify_plan_descriptions
from fastapi import APIRouter, Depends, Security
from packaging import version

if version.parse(pydantic.__version__) < version.parse("2.0.0"):
    from pydantic import BaseSettings
else:
    from pydantic_settings import BaseSettings

from ..authentication import get_current_principal
from ..re_manager_schemas import (
    DevicesAllowedResponse,
    DevicesExistingResponse,
    PlansAllowedResponse,
    PlansExistingResponse,
)
from ..resources import SERVER_RESOURCES as SR
from ..settings import get_settings
from ..utils import (
    get_api_access_manager,
    get_current_username,
    get_resource_access_manager,
    process_exception,
    validate_payload_keys,
)

logger = logging.getLogger(__name__)

plans_devices_router = APIRouter(prefix="/api")


@plans_devices_router.get(
    "/plans/allowed",
    response_model=PlansAllowedResponse,
    response_model_exclude_unset=True,
    summary="List plans allowed for the current user",
    description=(
        "Returns plans the current user's resource group is permitted to execute. "
        "Parameter: `reduced` (bool, default `False`) — when `True`, plan descriptions "
        "are simplified to save bandwidth. Required scope: `read:resources`."
    ),
    tags=["Plans"],
)
async def plans_allowed_handler(
    payload: dict = {},
    principal=Security(get_current_principal, scopes=["read:resources"]),
    settings: BaseSettings = Depends(get_settings),
    api_access_manager=Depends(get_api_access_manager),
    resource_access_manager=Depends(get_resource_access_manager),
):
    """
    Returns the lists of allowed plans. If boolean optional parameter ``reduced``
    is ``True``(default value is ``False`), then simplify plan descriptions before
    calling the API.
    """

    try:
        validate_payload_keys(payload, optional_keys=["reduced"])

        username = get_current_username(
            principal=principal, settings=settings, api_access_manager=api_access_manager
        )[0]
        user_group = resource_access_manager.get_resource_group(username)

        if "reduced" in payload:
            reduced = payload["reduced"]
            del payload["reduced"]
        else:
            reduced = False
        payload.update({"user_group": user_group})

        msg = await SR.RM.plans_allowed(**payload)
        if reduced and ("plans_allowed" in msg):
            msg["plans_allowed"] = simplify_plan_descriptions(msg["plans_allowed"])
    except Exception:
        process_exception()
    return msg


@plans_devices_router.get(
    "/devices/allowed",
    response_model=DevicesAllowedResponse,
    response_model_exclude_unset=True,
    summary="List devices allowed for the current user",
    description=(
        "Returns devices the current user's resource group is permitted to use. "
        "Required scope: `read:resources`."
    ),
    tags=["Devices"],
)
async def devices_allowed_handler(
    payload: dict = {},
    principal=Security(get_current_principal, scopes=["read:resources"]),
    settings: BaseSettings = Depends(get_settings),
    api_access_manager=Depends(get_api_access_manager),
    resource_access_manager=Depends(get_resource_access_manager),
):
    """
    Returns the lists of allowed devices.
    """
    try:
        username = get_current_username(
            principal=principal, settings=settings, api_access_manager=api_access_manager
        )[0]
        user_group = resource_access_manager.get_resource_group(username)

        payload.update({"user_group": user_group})

        msg = await SR.RM.devices_allowed(**payload)
    except Exception:
        process_exception()
    return msg


@plans_devices_router.get(
    "/plans/existing",
    response_model=PlansExistingResponse,
    response_model_exclude_unset=True,
    summary="List all plans registered in the worker",
    description=(
        "Returns all plans registered in the worker namespace, not filtered by user "
        "permissions. Parameter: `reduced` (bool, default `False`) — when `True`, plan "
        "descriptions are simplified to save bandwidth."
    ),
    tags=["Plans"],
)
async def plans_existing_handler(
    payload: dict = {},
):
    """
    Returns the lists of existing plans. If boolean optional parameter ``reduced``
    is ``True``(default value is ``False`), then simplify plan descriptions before
    calling the API.
    """
    try:
        validate_payload_keys(payload, optional_keys=["reduced"])

        if "reduced" in payload:
            reduced = payload["reduced"]
            del payload["reduced"]
        else:
            reduced = False

        msg = await SR.RM.plans_existing(**payload)
        if reduced and ("plans_existing" in msg):
            msg["plans_existing"] = simplify_plan_descriptions(msg["plans_existing"])
    except Exception:
        process_exception()

    return msg


@plans_devices_router.get(
    "/devices/existing",
    response_model=DevicesExistingResponse,
    response_model_exclude_unset=True,
    summary="List all devices registered in the worker",
    description=(
        "Returns all devices registered in the worker namespace, not filtered by user "
        "permissions. Required scope: `read:resources`."
    ),
    tags=["Devices"],
)
async def devices_existing_handler(
    payload: dict = {},
    principal=Security(get_current_principal, scopes=["read:resources"]),
):
    """
    Returns the lists of existing devices.
    """
    try:
        msg = await SR.RM.devices_existing(**payload)
    except Exception:
        process_exception()
    return msg
