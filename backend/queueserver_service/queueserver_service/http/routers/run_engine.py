import logging

from fastapi import APIRouter, Security

from ..authentication import get_current_principal
from ..re_manager_schemas import (
    ReMetadataResponse,
    RunsResponse,
    SuccessMsgResponse,
)
from ..resources import SERVER_RESOURCES as SR
from ..utils import (
    process_exception,
)

logger = logging.getLogger(__name__)

run_engine_router = APIRouter(prefix="/api")


@run_engine_router.post(
    "/re/pause",
    response_model=SuccessMsgResponse,
    response_model_exclude_unset=True,
    summary="Pause the Run Engine",
    description=(
        "Pause the currently running plan. Parameter: `option` — `'deferred'` (pause at the "
        "next checkpoint, safe) or `'immediate'` (pause at the next safe point). "
        "Required scope: `write:plan:control`."
    ),
    tags=["Run Engine"],
)
async def re_pause_handler(
    payload: dict = {},
    principal=Security(get_current_principal, scopes=["write:plan:control"]),
):
    """
    Pause Run Engine.
    """
    try:
        msg = await SR.RM.re_pause(**payload)
    except Exception:
        process_exception()
    return msg


@run_engine_router.post(
    "/re/resume",
    response_model=SuccessMsgResponse,
    response_model_exclude_unset=True,
    summary="Resume a paused plan",
    description=(
        "Resume execution of the currently paused plan. "
        "Required scope: `write:plan:control`."
    ),
    tags=["Run Engine"],
)
async def re_resume_handler(
    payload: dict = {}, principal=Security(get_current_principal, scopes=["write:plan:control"])
):
    """
    Run Engine: resume execution of a paused plan
    """
    try:
        msg = await SR.RM.re_resume(**payload)
    except Exception:
        process_exception()
    return msg


@run_engine_router.post(
    "/re/stop",
    response_model=SuccessMsgResponse,
    response_model_exclude_unset=True,
    summary="Stop a paused plan cleanly",
    description=(
        "Stop the currently paused plan. The plan is marked as successfully completed from "
        "the Run Engine's perspective. Required scope: `write:plan:control`."
    ),
    tags=["Run Engine"],
)
async def re_stop_handler(
    payload: dict = {}, principal=Security(get_current_principal, scopes=["write:plan:control"])
):
    """
    Run Engine: stop execution of a paused plan
    """
    try:
        msg = await SR.RM.re_stop(**payload)
    except Exception:
        process_exception()
    return msg


@run_engine_router.post(
    "/re/abort",
    response_model=SuccessMsgResponse,
    response_model_exclude_unset=True,
    summary="Abort a paused plan",
    description=(
        "Abort the currently paused plan. The plan is marked as failed, but Run Engine "
        "cleanup handlers still run (devices are returned to safe states). "
        "Required scope: `write:plan:control`."
    ),
    tags=["Run Engine"],
)
async def re_abort_handler(
    payload: dict = {}, principal=Security(get_current_principal, scopes=["write:plan:control"])
):
    """
    Run Engine: abort execution of a paused plan
    """
    try:
        msg = await SR.RM.re_abort(**payload)
    except Exception:
        process_exception()
    return msg


@run_engine_router.post(
    "/re/halt",
    response_model=SuccessMsgResponse,
    response_model_exclude_unset=True,
    summary="Halt a paused plan (no cleanup)",
    description=(
        "Halt the currently paused plan immediately without running cleanup handlers. More "
        "aggressive than `/re/abort` — use when cleanup itself is misbehaving. "
        "Required scope: `write:plan:control`."
    ),
    tags=["Run Engine"],
)
async def re_halt_handler(
    payload: dict = {}, principal=Security(get_current_principal, scopes=["write:plan:control"])
):
    """
    Run Engine: halt execution of a paused plan
    """
    try:
        msg = await SR.RM.re_halt(**payload)
    except Exception:
        process_exception()
    return msg


@run_engine_router.post(
    "/re/runs",
    response_model=RunsResponse,
    response_model_exclude_unset=True,
    summary="List runs produced by the current plan",
    description=(
        "Returns runs opened during the currently running plan. Parameter: `option` selects "
        "`'active'` (all), `'open'`, or `'closed'`; default `'active'`. See "
        "`/re/runs/active`, `/re/runs/open`, `/re/runs/closed` for convenience aliases. "
        "Required scope: `read:monitor`."
    ),
    tags=["Runs"],
)
async def re_runs_handler(payload: dict = {}, principal=Security(get_current_principal, scopes=["read:monitor"])):
    """
    Run Engine: download the list of active, open or closed runs (runs that were opened
    during execution of the currently running plan and combines the subsets of 'open' and
    'closed' runs.) The parameter ``options`` is used to select the category of runs
    (``'active'``, ``'open'`` or ``'closed'``). By default the API returns the active runs.
    """
    try:
        msg = await SR.RM.re_runs(**payload)
    except Exception:
        process_exception()
    return msg


@run_engine_router.get(
    "/re/runs/active",
    response_model=RunsResponse,
    response_model_exclude_unset=True,
    summary="List all runs produced by the current plan",
    description=(
        "Convenience alias for `POST /re/runs` with `option='active'`. Returns runs opened "
        "during the currently running plan (both open and closed). "
        "Required scope: `read:monitor`."
    ),
    tags=["Runs"],
)
async def re_runs_active_handler(principal=Security(get_current_principal, scopes=["read:monitor"])):
    """
    Run Engine: download the list of active runs (runs that were opened during execution of
    the currently running plan and combines the subsets of 'open' and 'closed' runs.)
    """
    try:
        params = {"option": "active"}
        msg = await SR.RM.re_runs(**params)
    except Exception:
        process_exception()
    return msg


@run_engine_router.get(
    "/re/runs/open",
    response_model=RunsResponse,
    response_model_exclude_unset=True,
    summary="List open runs produced by the current plan",
    description=(
        "Convenience alias for `POST /re/runs` with `option='open'`. Returns the subset of "
        "active runs that have been opened but not yet closed. "
        "Required scope: `read:monitor`."
    ),
    tags=["Runs"],
)
async def re_runs_open_handler(principal=Security(get_current_principal, scopes=["read:monitor"])):
    """
    Run Engine: download the subset of active runs that includes runs that were open, but not yet closed.
    """
    try:
        params = {"option": "open"}
        msg = await SR.RM.re_runs(**params)
    except Exception:
        process_exception()
    return msg


@run_engine_router.get(
    "/re/runs/closed",
    response_model=RunsResponse,
    response_model_exclude_unset=True,
    summary="List closed runs produced by the current plan",
    description=(
        "Convenience alias for `POST /re/runs` with `option='closed'`. Returns runs from "
        "the current plan that have been closed. Required scope: `read:monitor`."
    ),
    tags=["Runs"],
)
async def re_runs_closed_handler(principal=Security(get_current_principal, scopes=["read:monitor"])):
    """
    Run Engine: download the subset of active runs that includes runs that were already closed.
    """
    try:
        params = {"option": "closed"}
        msg = await SR.RM.re_runs(**params)
    except Exception:
        process_exception()
    return msg


@run_engine_router.get(
    "/re/metadata",
    response_model=ReMetadataResponse,
    response_model_exclude_unset=True,
    summary="Get metadata of the currently running plan",
    description=(
        "Returns the metadata of the plan currently executing in the Run Engine "
        "(run-specific kwargs, scan_id, etc.). Required scope: `read:monitor`."
    ),
    tags=["Runs"],
)
async def re_metadata(payload: dict = {}, principal=Security(get_current_principal, scopes=["read:monitor"])):
    """
    Run Engine: download the metadata of the currently running plan.
    """
    try:
        # send_request: re_metadata is an in-tree manager method that the
        # released bluesky-queueserver-api client does not expose yet.
        msg = await SR.RM.send_request(method="re_metadata", params=payload)
    except Exception:
        process_exception()
    return msg
