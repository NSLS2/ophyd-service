import asyncio
import logging

from fastapi import APIRouter, Security, WebSocket, WebSocketDisconnect

from ..authentication import get_current_principal, get_current_principal_websocket
from ..console_output import ConsoleOutputEventStream, StreamingResponseFromClass
from ..re_manager_schemas import (
    ConsoleOutputResponse,
    ConsoleOutputUidResponse,
    ConsoleOutputUpdateResponse,
)
from ..resources import SERVER_RESOURCES as SR
from ..utils import (
    process_exception,
    validate_payload_keys,
)

logger = logging.getLogger(__name__)

console_router = APIRouter(prefix="/api")


class WebSocketMonitor:
    """
    Works for sockets that only send data to clients (not receive).

    The class monitors the status of a socket connection. The property 'is_alive' returns True
    until the socket is disconnected. The purpose of the class is to break the loop in the
    implementation of the socket that only sends data to a client when the application
    is closed. If there is no data to send, the loop continues to run indefinitely and
    prevents the application from closing properly. No better solution was found.
    """

    def __init__(self, websocket):
        self._websocket = websocket
        self._is_alive = True
        self._task_ref = None

    async def _task(self):
        while True:
            try:
                await asyncio.sleep(1)
                try:
                    # The following will raise an exception if the socket is disconnected.
                    await asyncio.wait_for(self._websocket.receive(), timeout=0.01)
                except asyncio.TimeoutError:
                    # The socket is still connected.
                    pass
            except Exception:
                self._is_alive = False
                break

    def start(self):
        self._task_ref = asyncio.create_task(self._task())

    @property
    def is_alive(self):
        return self._is_alive


@console_router.get(
    "/stream_console_output",
    summary="Stream captured console output (Server-Sent Events)",
    description=(
        "Returns a text/event-stream of captured worker stdout/stderr. The connection "
        "stays open and the client reads lines as they arrive. "
        "Required scope: `read:console`."
    ),
    tags=["Console Output"],
)
def stream_console_output(principal=Security(get_current_principal, scopes=["read:console"])):
    queues_set = SR.console_output_loader.queues_set
    stm = ConsoleOutputEventStream(queues_set=queues_set)
    sr = StreamingResponseFromClass(stm, media_type="text/plain")
    return sr


@console_router.get(
    "/console_output",
    response_model=ConsoleOutputResponse,
    response_model_exclude_unset=True,
    summary="Get buffered console output",
    description=(
        "Returns the most recent lines of captured worker console output as a text blob. "
        "Parameter: `nlines` (int, default 200). Required scope: `read:console`."
    ),
    tags=["Console Output"],
)
async def console_output(payload: dict = {}, principal=Security(get_current_principal, scopes=["read:console"])):
    try:
        n_lines = payload.get("nlines", 200)
        text = await SR.console_output_loader.get_text_buffer(n_lines)
    except Exception:
        process_exception()

    # Add 'success' and 'msg' so that the API is compatible with other QServer API.
    return {"success": True, "msg": "", "text": text}


@console_router.get(
    "/console_output/uid",
    response_model=ConsoleOutputUidResponse,
    response_model_exclude_unset=True,
    summary="Get the console-output buffer UID",
    description=(
        "Returns the UID of the current console-output buffer. Pair with `/console_output` "
        "to detect when the buffer has been reset (for example after the environment is "
        "restarted). Required scope: `read:console`."
    ),
    tags=["Console Output"],
)
def console_output_uid(principal=Security(get_current_principal, scopes=["read:console"])):
    """
    UID of the text buffer. Use with ``console_output`` API.
    """
    try:
        uid = SR.console_output_loader.text_buffer_uid
    except Exception:
        process_exception()
    return {"success": True, "msg": "", "console_output_uid": uid}


@console_router.get(
    "/console_output_update",
    response_model=ConsoleOutputUpdateResponse,
    response_model_exclude_unset=True,
    summary="Fetch new console messages since last UID",
    description=(
        "Returns console-output messages accumulated since the `last_msg_uid` supplied by "
        "the caller. Initialize with `'ALL'` to receive all buffered messages; on each "
        "subsequent call, pass back the UID from the previous response. If the UID is not "
        "found in the buffer (rollover), an empty message list and a fresh UID are "
        "returned. Required scope: `read:console`."
    ),
    tags=["Console Output"],
)
def console_output_update(payload: dict, principal=Security(get_current_principal, scopes=["read:console"])):
    """
    Download the list of new messages that were accumulated at the server. The API
    accepts a required parameter ``last_msg_uid`` with UID of the last downloaded message.
    If the UID is not found in the buffer, an empty message list and valid UID is
    returned. If UID is ``"ALL"``, then all accumulated messages in the buffer is
    returned. If UID is found in the buffer, then the list of new messages is returned.

    At the client: initialize the system by sending request with ``last_msg_uid`` set
    to random string or ``"ALL"``. In each request use ``last_msg_uid`` returned by the previous
    request to download new messages.
    """
    try:
        validate_payload_keys(payload, required_keys=["last_msg_uid"])

        response = SR.console_output_loader.get_new_msgs(last_msg_uid=payload["last_msg_uid"])
        # Add 'success' and 'msg' so that the API is compatible with other QServer API.
        response.update({"success": True, "msg": ""})
    except Exception:
        process_exception()

    return response


@console_router.websocket("/console_output/ws")
async def console_output_ws(websocket: WebSocket, scopes=["read:console"]):
    principal = get_current_principal_websocket(websocket=websocket, scopes=scopes)
    if not principal:
        await websocket.close(code=4001, reason="Invalid token")
        return

    await websocket.accept()
    q = SR.console_output_stream.add_queue(websocket)
    wsmon = WebSocketMonitor(websocket)
    wsmon.start()
    try:
        while wsmon.is_alive:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=1)
                await websocket.send_text(msg)
            except asyncio.TimeoutError:
                pass
            except RuntimeError:  # 'send' after the client is disconnected
                pass
    except WebSocketDisconnect:
        pass
    finally:
        SR.console_output_stream.remove_queue(websocket)


@console_router.websocket("/status/ws")
async def status_ws(websocket: WebSocket, scopes=["read:monitor"]):
    principal = get_current_principal_websocket(websocket=websocket, scopes=scopes)
    if not principal:
        await websocket.close(code=4001, reason="Invalid token")
        return

    await websocket.accept()
    q = SR.system_info_stream.add_queue_status(websocket)
    wsmon = WebSocketMonitor(websocket)
    wsmon.start()

    try:
        while wsmon.is_alive:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=1)
                await websocket.send_text(msg)
            except asyncio.TimeoutError:
                pass
            except RuntimeError:  # 'send' after the client is disconnected
                pass
    except WebSocketDisconnect:
        pass
    finally:
        SR.system_info_stream.remove_queue_status(websocket)


@console_router.websocket("/info/ws")
async def info_ws(websocket: WebSocket, scopes=["read:monitor"]):
    principal = get_current_principal_websocket(websocket=websocket, scopes=scopes)
    if not principal:
        await websocket.close(code=4001, reason="Invalid token")
        return

    await websocket.accept()
    q = SR.system_info_stream.add_queue_info(websocket)
    wsmon = WebSocketMonitor(websocket)
    wsmon.start()
    try:
        while wsmon.is_alive:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=1)
                await websocket.send_text(msg)
            except asyncio.TimeoutError:
                pass
            except RuntimeError:  # 'send' after the client is disconnected
                pass
    except WebSocketDisconnect:
        pass
    finally:
        SR.system_info_stream.remove_queue_info(websocket)
