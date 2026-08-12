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
    FunctionExecuteResponse,
    SuccessMsgResponse,
    TaskResultResponse,
    TaskStatusResponse,
    TaskUidResponse,
)
from ..resources import SERVER_RESOURCES as SR
from ..settings import get_settings
from ..utils import (
    get_api_access_manager,
    get_current_username,
    get_resource_access_manager,
    process_exception,
)

logger = logging.getLogger(__name__)

execution_router = APIRouter(prefix="/api")


@execution_router.post(
    "/function/execute",
    response_model=FunctionExecuteResponse,
    response_model_exclude_unset=True,
    summary="Execute a function in the worker",
    description=(
        "Execute a function defined in the worker's startup scripts. Parameter: `item` "
        "(function-item spec with `name`, `args`, `kwargs`). Returns a `task_uid` — poll "
        "`/task/status` and `/task/result` for progress and output. "
        "Required scope: `write:execute`."
    ),
    tags=["Scripts & Functions"],
)
async def function_execute_handler(
    payload: dict,
    principal=Security(get_current_principal, scopes=["write:execute"]),
    settings: BaseSettings = Depends(get_settings),
    api_access_manager=Depends(get_api_access_manager),
    resource_access_manager=Depends(get_resource_access_manager),
):
    """
    Execute function defined in startup scripts in RE Worker environment.
    """
    try:
        username = get_current_username(
            principal=principal, settings=settings, api_access_manager=api_access_manager
        )[0]
        displayed_name = api_access_manager.get_displayed_user_name(username)
        user_group = resource_access_manager.get_resource_group(username)
        payload.update({"user": displayed_name, "user_group": user_group})

        if "item" not in payload:
            # We can not use API, so let the server handle the parameters
            msg = await SR.RM.send_request(method="function_execute", params=payload)
        else:
            msg = await SR.RM.function_execute(**payload)
    except Exception:
        process_exception()
    return msg


@execution_router.post(
    "/script/upload",
    response_model=TaskUidResponse,
    response_model_exclude_unset=True,
    summary="Upload and execute a Python script in the worker",
    description=(
        "Send a Python source string to the worker for execution. Parameter: `script` (str). "
        "Side-effects (new plans, new devices, redefined functions) are visible in "
        "subsequent calls after an `/environment/update`. Returns a `task_uid`. "
        "Required scope: `write:scripts`."
    ),
    tags=["Scripts & Functions"],
)
async def script_upload_handler(
    payload: dict, principal=Security(get_current_principal, scopes=["write:scripts"])
):
    """
    Upload and execute script in RE Worker environment.
    """
    try:
        if "script" not in payload:
            # We can not use API, so let the server handle the parameters
            msg = await SR.RM.send_request(method="script_upload", params=payload)
        else:
            msg = await SR.RM.script_upload(**payload)
    except Exception:
        process_exception()
    return msg


@execution_router.get(
    "/task/status",
    response_model=TaskStatusResponse,
    response_model_exclude_unset=True,
    summary="Get status of one or more worker tasks",
    description=(
        "Returns the status of tasks started via `/function/execute` or `/script/upload`. "
        "Parameter: `task_uid` (str for a single task, or list of str for multiple). "
        "Required scope: `read:monitor`."
    ),
    tags=["Scripts & Functions"],
)
async def task_status(payload: dict, principal=Security(get_current_principal, scopes=["read:monitor"])):
    """
    Return status of one or more running tasks.
    """
    try:
        if "task_uid" not in payload:
            # We can not use API, so let the server handle the parameters
            msg = await SR.RM.send_request(method="task_status", params=payload)
        else:
            msg = await SR.RM.task_status(**payload)
    except Exception:
        process_exception()
    return msg


@execution_router.get(
    "/task/result",
    response_model=TaskResultResponse,
    response_model_exclude_unset=True,
    summary="Get result of a worker task",
    description=(
        "Returns the result (or error) of a completed task, or the in-progress status if "
        "still running. Parameter: `task_uid` (str). "
        "Required scope: `read:monitor`."
    ),
    tags=["Scripts & Functions"],
)
async def task_result(payload: dict, principal=Security(get_current_principal, scopes=["read:monitor"])):
    """
    Return result of execution of a running or completed task.
    """
    try:
        if "task_uid" not in payload:
            # We can not use API, so let the server handle the parameters
            msg = await SR.RM.send_request(method="task_result", params=payload)
        else:
            msg = await SR.RM.task_result(**payload)
    except Exception:
        process_exception()
    return msg


@execution_router.post(
    "/kernel/interrupt",
    response_model=SuccessMsgResponse,
    response_model_exclude_unset=True,
    summary="Interrupt the worker IPython kernel",
    description=(
        "Send a keyboard-interrupt to the IPython-kernel-based worker. No-op for worker "
        "configurations that do not use an IPython kernel. "
        "Required scope: `write:queue:control`."
    ),
    tags=["Scripts & Functions"],
)
async def kernel_interrupt_handler(
    payload: dict = {}, principal=Security(get_current_principal, scopes=["write:queue:control"])
):
    """
    Interrupt IPython kernel.
    """
    try:
        msg = await SR.RM.kernel_interrupt(**payload)
    except Exception:
        process_exception()
    return msg
