# Ported from bluesky-queueserver-api (BSD-3), commit e3fb37f1 (v0.0.13 + 6 commits, 2026-04-07).
# Trimmed to the async 0MQ path; imports rewired to in-tree queueserver_service modules.

import asyncio
import threading
import uuid

from queueserver_service.manager.output_streaming import ReceiveConsoleOutputAsync

from .comm_base import RequestTimeoutError


class _ConsoleMonitor:
    def __init__(self, *, max_lines):
        self._monitor_enabled = False
        self._monitor_init()

        self._buffers_modified_event = threading.Event()

        self._text = {}
        self._set_new_text_uid()

        self._text_buffer = []
        self._text_clear()
        self._text_max_lines = max(max_lines, 0)

    def _text_generate(self, nlines):
        n_text_buffer = len(self._text_buffer)
        nlines = max(nlines, 0) if (nlines is not None) else n_text_buffer

        if self._text_buffer and self._text_buffer[-1] == "":
            nlines = min(nlines, n_text_buffer - 1)
            if nlines not in self._text:
                text = "\n".join(self._text_buffer[-nlines - 1 : -1])
                self._text[nlines] = text
            else:
                text = self._text[nlines]
        else:
            nlines = min(nlines, n_text_buffer)
            if nlines not in self._text:
                text = "\n".join(self._text_buffer[-nlines:])
                self._text[nlines] = text
            else:
                text = self._text[nlines]
        return text

    def _set_new_text_uid(self):
        self._text_uid = str(uuid.uuid4())

    def _text_clear(self):
        self._text.clear()
        self._set_new_text_uid()

        self._text_line = 0
        self._text_pos = 0
        self._text_buffer.clear()

    def _add_msg_to_text_buffer(self, response):
        # Setting max number of lines to 0 disables text processing
        if not self._text_max_lines:
            return

        msg = response["msg"]

        pattern_new_line = "\n"
        pattern_cr = "\r"
        pattern_up_one_line = "\x1b\x5b\x41"  # ESC [#A

        patterns = {"new_line": pattern_new_line, "cr": pattern_cr, "one_line_up": pattern_up_one_line}

        while msg:
            indices = {k: msg.find(v) for k, v in patterns.items()}
            indices_nonzero = [_ for _ in indices.values() if (_ >= 0)]
            next_ind = min(indices_nonzero) if indices_nonzero else len(msg)

            # The following algorithm requires that there is at least one line in the list.
            if not self._text_buffer:
                self._text_buffer = [""]
                self._text_line = 0
                self._text_pos = 0

            if next_ind != 0:
                # Add a line to the current line and position
                substr = msg[:next_ind]
                msg = msg[next_ind:]

                # Extend the current line with spaces if needed
                line_len = len(self._text_buffer[self._text_line])
                if line_len < self._text_pos:
                    self._text_buffer[self._text_line] += " " * (self._text_pos - line_len)

                line = self._text_buffer[self._text_line]
                self._text_buffer[self._text_line] = (
                    line[: self._text_pos] + substr + line[self._text_pos + len(substr) :]
                )
                self._text_pos = self._text_pos + len(substr)

            elif indices["new_line"] == 0:
                self._text_line += 1
                if self._text_line >= len(self._text_buffer):
                    self._text_buffer.insert(self._text_line, "")
                self._text_pos = 0
                msg = msg[len(patterns["new_line"]) :]

            elif indices["cr"] == 0:
                self._text_pos = 0
                msg = msg[len(patterns["cr"]) :]

            elif indices["one_line_up"] == 0:
                if self._text_line:
                    self._text_line -= 1
                msg = msg[len(patterns["one_line_up"]) :]

        self._set_new_text_uid()

    def _adjust_text_buffer_size(self):
        if self._text_buffer and self._text_buffer[-1] == "":
            # Do not count an empty string at the end
            max_lines = self._text_max_lines + 1
        else:
            max_lines = self._text_max_lines

        if len(self._text_buffer) > max_lines:
            # Remove extra lines from the beginning of the list
            n_remove = len(self._text_buffer) - max_lines
            # In majority of cases only 1 (or a few) elements are removed
            for _ in range(n_remove):
                self._text_buffer.pop(0)
            self._text_line = max(self._text_line - n_remove, 0)

        self._set_new_text_uid()

    def _monitor_init(self):
        raise NotImplementedError()

    def _clear(self):
        raise NotImplementedError()

    def _monitor_enable(self):
        raise NotImplementedError()

    @property
    def text_uid(self):
        """UID of the current text buffer; changes whenever the buffer contents change."""
        return self._text_uid

    @property
    def text_max_lines(self):
        """Get/set the maximum size of the text buffer."""
        return self._text_max_lines

    @text_max_lines.setter
    def text_max_lines(self, max_lines):
        max_lines = max(max_lines, 0)
        self._text_max_lines = max_lines
        self._adjust_text_buffer_size()

    @property
    def enabled(self):
        """Indicates if monitoring is enabled."""
        return self._monitor_enabled

    def enable(self):
        """Enable monitoring of the console output."""
        if not self._monitor_enabled:
            self._monitor_enable()

    def disable(self):
        """Disable monitoring of the console output (does not immediately stop the task)."""
        self._monitor_enabled = False

    def clear(self):
        """Clear the message buffer."""
        self._clear()

    def __del__(self):
        self.disable()


class _ConsoleMonitor_Async(_ConsoleMonitor):
    def __init__(self, *, max_msgs, max_lines):
        self._msg_queue_max = max_msgs
        self._msg_queue = asyncio.Queue(maxsize=max_msgs)

        self._monitor_task = None  # Thread or asyncio task
        self._monitor_task_running = asyncio.Event()
        self._monitor_task_running.set()

        self._monitor_task_lock = asyncio.Lock()
        self._text_buffer_lock = asyncio.Lock()

        super().__init__(max_lines=max_lines)

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

    async def text(self, nlines=None):
        """Return text representation of the console output (up to ``nlines`` lines)."""
        async with self._text_buffer_lock:
            text = self._text_generate(nlines=nlines)
        return text


class ConsoleMonitor_ZMQ_Async(_ConsoleMonitor_Async):
    """
    Console Monitor API (0MQ, async). Monitors console output published by RE Manager
    over 0MQ. Must be instantiated in a running event loop.
    """

    def __init__(self, *, zmq_info_addr, zmq_encoding, poll_timeout, max_msgs, max_lines):
        self._zmq_subscribe_addr = zmq_info_addr
        self._zmq_encoding = zmq_encoding
        self._monitor_poll_timeout = poll_timeout
        super().__init__(max_msgs=max_msgs, max_lines=max_lines)

    def _monitor_init(self):
        self._rco = ReceiveConsoleOutputAsync(
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

                async with self._text_buffer_lock:
                    self._add_msg_to_queue(msg)
                    self._add_msg_to_text_buffer(msg)
                    self._adjust_text_buffer_size()

            except TimeoutError:
                # No published messages are detected
                pass
            except asyncio.QueueFull:
                # Queue is full, ignore the new messages
                pass

    def _clear(self):
        self._text_clear()
        try:
            while True:
                self._msg_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
