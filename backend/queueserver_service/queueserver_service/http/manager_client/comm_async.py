# Ported from bluesky-queueserver-api (BSD-3), commit e3fb37f1 (v0.0.13 + 6 commits, 2026-04-07).
# Trimmed to the async 0MQ path; imports rewired to in-tree queueserver_service modules.

from queueserver_service.common.comms import ZMQCommSendAsync

from .comm_base import ReManagerAPI_ZMQ_Base
from .console_monitor import ConsoleMonitor_ZMQ_Async
from .system_info_monitor import SystemInfoMonitor_ZMQ_Async


class ReManagerComm_ZMQ_Async(ReManagerAPI_ZMQ_Base):
    def _init_console_monitor(self):
        self._console_monitor = ConsoleMonitor_ZMQ_Async(
            zmq_info_addr=self._zmq_info_addr,
            zmq_encoding=self._zmq_encoding,
            poll_timeout=self._console_monitor_poll_timeout,
            max_msgs=self._console_monitor_max_msgs,
            max_lines=self._console_monitor_max_lines,
        )

    def _init_system_info_monitor(self):
        self._system_info_monitor = SystemInfoMonitor_ZMQ_Async(
            zmq_info_addr=self._zmq_info_addr,
            zmq_encoding=self._zmq_encoding,
            poll_timeout=self._system_info_monitor_poll_timeout,
            max_msgs=self._system_info_monitor_max_msgs,
        )

    def _create_client(
        self,
        *,
        zmq_control_addr,
        zmq_encoding,
        timeout_recv,
        timeout_send,
        zmq_public_key,
    ):
        return ZMQCommSendAsync(
            zmq_server_address=zmq_control_addr,
            encoding=zmq_encoding,
            timeout_recv=int(timeout_recv * 1000),  # Convert to ms
            timeout_send=int(timeout_send * 1000),  # Convert to ms
            raise_exceptions=True,
            server_public_key=zmq_public_key,
        )

    async def send_request(self, *, method, params=None):
        """Send a request to RE Manager over 0MQ and return the response dictionary."""
        try:
            response = await self._client.send_message(method=method, params=params)
        except Exception:
            self._process_comm_exception(method=method, params=params)
        self._check_response(request={"method": method, "params": params}, response=response)

        return response

    async def close(self):
        """Disable monitors, close the 0MQ socket and stop background tasks."""
        self._is_closing = True
        await self._console_monitor.disable_wait(timeout=self._console_monitor_poll_timeout * 10)
        await self._system_info_monitor.disable_wait(timeout=self._system_info_monitor_poll_timeout * 10)
        self._client.close()

    def __del__(self):
        self._is_closing = True
