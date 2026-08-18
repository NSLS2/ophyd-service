# Ported from bluesky-queueserver-api (BSD-3), commit e3fb37f1 (v0.0.13 + 6 commits, 2026-04-07).
# Trimmed to the async 0MQ path; imports rewired to in-tree queueserver_service modules.

import enum
import os
from collections.abc import Iterable, Mapping

from queueserver_service.common.comms import CommTimeoutError

from ._defaults import (
    default_allow_request_fail_exceptions,
    default_console_monitor_max_lines,
    default_console_monitor_max_msgs,
    default_console_monitor_poll_timeout,
    default_system_info_monitor_max_msgs,
    default_system_info_monitor_poll_timeout,
    default_zmq_request_timeout_recv,
    default_zmq_request_timeout_send,
)


class RequestParameterError(Exception): ...


class RequestTimeoutError(TimeoutError):
    def __init__(self, msg, request):
        msg = f"Request timeout: {msg}"
        self.request = request
        super().__init__(msg)


class RequestFailedError(Exception):
    def __init__(self, request, response):
        msg = response.get("msg", "") if isinstance(response, Mapping) else str(response)
        msg = msg or "(no error message)"
        msg = f"Request failed: {msg}"
        self.request = request
        self.response = response
        super().__init__(msg)


class Protocols(enum.Enum):
    ZMQ = "ZMQ"
    HTTP = "HTTP"


class ReManagerAPI_Base:
    RequestParameterError = RequestParameterError
    RequestTimeoutError = RequestTimeoutError
    RequestFailedError = RequestFailedError

    Protocols = Protocols

    def __init__(self, *, request_fail_exceptions=True):
        # Raise exceptions if request fails (success=False)
        self._request_fail_exceptions = request_fail_exceptions
        self._console_monitor = None
        self._system_info_monitor = None

        self._protocol = None
        self._pass_user_info = True

        self._is_closing = False  # Set True to exit all background tasks.

    @property
    def request_fail_exceptions_enabled(self):
        """
        Enable or disable ``RequestFailedError`` exceptions (*boolean*). The exceptions are
        raised when the request fails, i.e. the response received from the server contains
        ``'success'==False``. The property does not influence timeout errors.
        """
        return self._request_fail_exceptions

    @request_fail_exceptions_enabled.setter
    def request_fail_exceptions_enabled(self, v):
        self._request_fail_exceptions = bool(v)

    def _check_response(self, *, request, response):
        """
        Check if response is a dictionary and has ``"success": True``. Raise an exception
        if the request is considered failed and exceptions are allowed. If response is
        a dictionary and contains no ``"success"``, then it is considered successful.
        """
        if self._request_fail_exceptions:
            # The response must be a list or a dictionary. If the response is a dictionary
            #   and the key 'success': False, then consider the request failed. If there
            #   is not 'success' key, then consider the request successful.
            is_iterable = isinstance(response, Iterable) and not isinstance(response, str)
            is_mapping = isinstance(response, Mapping)
            if not any([is_iterable, is_mapping]) or (is_mapping and not response.get("success", True)):
                raise self.RequestFailedError(request, response)

    @property
    def console_monitor(self):
        """
        Reference to a ``console_monitor``. Console monitor is an instance of
        a matching ``ConsoleMonitor_...`` class and supports methods ``enable()``,
        ``disable()``, ``disable_wait()``, ``clear()``, ``next_msg()`` and
        property ``enabled``. See documentation for the respective class
        for more details.
        """
        return self._console_monitor

    @property
    def system_info_monitor(self):
        """
        Reference to a ``system_info_monitor``. System Info monitor is an instance of
        a matching ``SystemInfoMonitor_...`` class. See documentation for the respective
        class for more details.
        """
        return self._system_info_monitor

    def _init_console_monitor(self):
        raise NotImplementedError()

    def _init_system_info_monitor(self):
        raise NotImplementedError()

    @property
    def protocol(self):
        """
        Indicates the protocol used for communication (ZMQ or HTTP). The returned value is of
        ``REManagerAPI.Protocols`` enum type.
        """
        if self._protocol is None:
            raise ValueError("Protocol is not defined")
        return self._protocol


class ReManagerAPI_ZMQ_Base(ReManagerAPI_Base):
    def __init__(
        self,
        *,
        zmq_control_addr=None,
        zmq_info_addr=None,
        zmq_encoding="json",
        timeout_recv=default_zmq_request_timeout_recv,
        timeout_send=default_zmq_request_timeout_send,
        console_monitor_poll_timeout=default_console_monitor_poll_timeout,
        console_monitor_max_msgs=default_console_monitor_max_msgs,
        console_monitor_max_lines=default_console_monitor_max_lines,
        system_info_monitor_poll_timeout=default_system_info_monitor_poll_timeout,
        system_info_monitor_max_msgs=default_system_info_monitor_max_msgs,
        zmq_public_key=None,
        request_fail_exceptions=default_allow_request_fail_exceptions,
    ):
        super().__init__(request_fail_exceptions=request_fail_exceptions)

        self._protocol = self.Protocols.ZMQ

        zmq_control_addr = zmq_control_addr or os.environ.get("QSERVER_ZMQ_CONTROL_ADDRESS", None)
        zmq_info_addr = zmq_info_addr or os.environ.get("QSERVER_ZMQ_INFO_ADDRESS", None)
        zmq_public_key = zmq_public_key or os.environ.get("QSERVER_ZMQ_PUBLIC_KEY", None)

        self._zmq_encoding = zmq_encoding
        self._zmq_info_addr = zmq_info_addr
        self._console_monitor_poll_timeout = console_monitor_poll_timeout
        self._console_monitor_max_msgs = console_monitor_max_msgs
        self._console_monitor_max_lines = console_monitor_max_lines
        self._system_info_monitor_poll_timeout = system_info_monitor_poll_timeout
        self._system_info_monitor_max_msgs = system_info_monitor_max_msgs

        self._client = self._create_client(
            zmq_control_addr=zmq_control_addr,
            zmq_encoding=zmq_encoding,
            timeout_recv=timeout_recv,
            timeout_send=timeout_send,
            zmq_public_key=zmq_public_key,
        )

        self._init_console_monitor()
        self._init_system_info_monitor()

    def _create_client(
        self,
        *,
        zmq_control_addr,
        timeout_recv,
        timeout_send,
        zmq_public_key,
    ):
        raise NotImplementedError()

    def _process_comm_exception(self, *, method, params):
        try:
            raise
        except CommTimeoutError as ex:
            raise self.RequestTimeoutError(ex, {"method": method, "params": params}) from ex
