# Ported from bluesky-queueserver-api (BSD-3), commit e3fb37f1 (v0.0.13 + 6 commits, 2026-04-07).
# Trimmed to the async 0MQ path; imports rewired to in-tree queueserver_service modules.

import asyncio

from queueserver_service.manager.output_streaming import ReceiveSystemInfoAsync

from .comm_base import RequestTimeoutError


class _SystemInfoMonitor:
    def __init__(self):
        self._monitor_enabled = False
        self._monitor_init()

    def _monitor_init(self):
        raise NotImplementedError()

    def _clear(self):
        raise NotImplementedError()

    def _monitor_enable(self):
        raise NotImplementedError()

    @property
    def enabled(self):
        """Indicates if monitoring is enabled."""
        return self._monitor_enabled

    def enable(self):
        """Enable monitoring of the system info."""
        if not self._monitor_enabled:
            self._monitor_enable()

    def disable(self):
        """Disable monitoring of the system info (does not immediately stop the task)."""
        self._monitor_enabled = False

    def clear(self):
        """Clear the message buffer."""
        self._clear()

    def __del__(self):
        self.disable()


class _SystemInfoMonitor_Async(_SystemInfoMonitor):
    def __init__(self, *, max_msgs):
        self._msg_queue_max = max_msgs
        self._msg_queue = asyncio.Queue(maxsize=max_msgs)

        self._monitor_task = None  # Thread or asyncio task
        self._monitor_task_running = asyncio.Event()
        self._monitor_task_running.set()

        self._monitor_task_lock = asyncio.Lock()

        super().__init__()

    def _add_msg_to_queue(self, msg):
        if self._msg_queue_max:
            self._msg_queue.put_nowait(msg)

    def _monitor_enable(self):
        self._monitor_task = asyncio.create_task(self._task_receive_msgs())
        self._monitor_enabled = True

    async def disable_wait(self, *, timeout=2):
        """Disable monitoring and wait for the background task to stop."""
        self.disable()
        await asyncio.wait_for(self._monitor_task_running.wait(), timeout=timeout)

    async def next_msg(self, timeout=None):
        """Return the next message from the buffer; raise ``RequestTimeoutError`` if none arrives."""
        try:
            if timeout:
                return await asyncio.wait_for(self._msg_queue.get(), timeout=timeout)
            else:
                return self._msg_queue.get_nowait()
        except (asyncio.QueueEmpty, asyncio.TimeoutError):
            raise RequestTimeoutError(f"No message was received (timeout={timeout})", request={})


class SystemInfoMonitor_ZMQ_Async(_SystemInfoMonitor_Async):
    """
    System Info Monitor API (0MQ, async). Monitors system info published by RE Manager
    over 0MQ. Must be instantiated in a running event loop.
    """

    def __init__(self, *, zmq_info_addr, zmq_encoding, poll_timeout, max_msgs):
        self._zmq_subscribe_addr = zmq_info_addr
        self._zmq_encoding = zmq_encoding
        self._monitor_poll_timeout = poll_timeout
        super().__init__(max_msgs=max_msgs)

    def _monitor_init(self):
        self._rco = ReceiveSystemInfoAsync(
            zmq_subscribe_addr=self._zmq_subscribe_addr,
            encoding=self._zmq_encoding,
            timeout=int(self._monitor_poll_timeout * 1000),
        )

    async def _task_receive_msgs(self):
        async with self._monitor_task_lock:
            if not self._monitor_task_running.is_set():
                return
            self._monitor_task_running.clear()
            self.clear()

            self._rco.subscribe()

        while True:
            async with self._monitor_task_lock:
                if not self._monitor_enabled:
                    self._rco.unsubscribe()
                    self._monitor_task_running.set()
                    break

            try:
                msg = await self._rco.recv()
                self._add_msg_to_queue(msg)

            except TimeoutError:
                # No published messages are detected
                pass
            except asyncio.QueueFull:
                # Queue is full, ignore the new messages
                pass

    def _clear(self):
        try:
            while True:
                self._msg_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
