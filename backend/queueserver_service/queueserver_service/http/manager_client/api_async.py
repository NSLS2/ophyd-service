# Ported from bluesky-queueserver-api (BSD-3), commit e3fb37f1 (v0.0.13 + 6 commits, 2026-04-07).
# Trimmed to the async 0MQ path; imports rewired to in-tree queueserver_service modules.

import asyncio
import copy
import time as ttime

from ._defaults import default_wait_timeout
from .api_base import API_Base, WaitMonitor


class API_Async_Mixin(API_Base):
    def __init__(self, *, status_expiration_period, status_polling_period):

        super().__init__(
            status_expiration_period=status_expiration_period,
            status_polling_period=status_polling_period,
        )

        self._event_status_get = asyncio.Event()
        self._status_get_cb = []  # A list of callbacks
        self._status_get_cb_lock = asyncio.Lock()
        self._wait_cb = []

        # Use tasks instead of threads
        self._task_status_get = asyncio.create_task(self._task_status_get_func())
        self._task_status_get = asyncio.create_task(self._task_status_poll_func())

    def _validate_loop(self, loop):
        """
        Check if the loop is in valid state to instantiate the class outside asyncio context.
        """
        if loop is None:
            raise RuntimeError(
                "Failed to instantiate REManagerAPI class. 'loop' argument is required if REManagerAPI "
                "is instantiated outside asyncio context."
            )
        if not loop.is_running():
            raise RuntimeError("Failed to instantiate REManagerAPI class. The provided 'loop' is not running.")

    async def _event_wait(self, event, timeout):
        """
        Emulation of ``threading.Event.wait`` with timeout.
        """
        try:
            await asyncio.wait_for(event.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def _task_status_get_func(self):
        """
        The coroutine is run as a background task (not awaited). It periodically checks if
        ``self._event_status_get`` is set. If the event is set, then the function loads
        (if needed) and processes RE Manager status.
        """
        while True:
            load_status = await self._event_wait(self._event_status_get, timeout=0.1)
            if load_status:
                if self._status_timestamp:
                    dt = ttime.time() - self._status_timestamp
                    dt = dt if (dt >= 0) else None
                else:
                    dt = None

                if (dt is None) or (dt > self._status_expiration_period):
                    status, raised_exception = None, None
                    try:
                        status = await self._load_status()
                    except Exception as ex:
                        raised_exception = ex

                    if status is not None:
                        self._status_timestamp = ttime.time()

                    self._status_current = status
                    self._status_exception = raised_exception

                async with self._status_get_cb_lock:
                    # Call each 'status_get' callback with current status/exception
                    for cb in self._status_get_cb:
                        cb(self._status_current, self._status_exception)
                    self._status_get_cb.clear()

                    # Update 'wait' callbacks. Even if the status is not reloaded,
                    #   the callbacks still check if there are timeouts.
                    n_cb = 0  # The number of wait callbacks
                    for cb in self._wait_cb.copy():
                        if cb(self._status_current):
                            self._wait_cb.pop(n_cb)
                        else:
                            n_cb += 1

                self._event_status_get.clear()

            if self._is_closing:
                break

    async def _task_status_poll_func(self):
        while True:
            await asyncio.sleep(self._status_polling_period)

            async with self._status_get_cb_lock:
                if len(self._wait_cb):
                    self._event_status_get.set()

            if self._is_closing:
                break

    async def _load_status(self):
        """
        Returns status of RE Manager.
        """
        return await self.send_request(method="status")

    async def _wait_for_condition(self, *, condition, timeout, monitor, reset_time_start=True):
        """
        Blocking function, which is waiting for the returned status to satisfy
        the specified conditions. The function is raises ``WaitTimeoutError``
        if timeout occurs. The ``timeout`` parameter is mandatory, but could be
        set to a very large value if needed.

        Parameters
        ----------
        condition: callable
           Condition is a function (any callable), which is waiting for the returned
           status to satisfy certain fixed set of conditions. For example, the function
           which waits for the manager status to become idle:

           .. code-block:: python

                def condition(status):
                    return (status["manager_state"] == "idle")

        timeout: float
            timeout in seconds
        monitor: WaitMonitor or None
            Reference to wait monitor
        reset_time_start: boolean (optional, default: True)
            Set ``False`` to use start time that is already set in the monitor.
            It is automatically set ``True`` if ``monitor`` is ``None``.
        """

        timeout_occurred = False
        wait_cancelled = False

        if not monitor:
            reset_time_start = True
            monitor = WaitMonitor()
        if reset_time_start:
            monitor._time_start = ttime.time()
        monitor.set_timeout(timeout)

        event = asyncio.Event()

        def cb(status):
            nonlocal timeout_occurred, wait_cancelled
            result = condition(status) if status else False

            if not result and (monitor.time_elapsed > monitor.timeout):
                timeout_occurred = True
                result = True
            elif monitor.is_cancelled:
                wait_cancelled = True
                result = True

            if result:
                event.set()

            return result

        try:
            async with self._status_get_cb_lock:
                self._wait_cb.append(cb)

            await event.wait()
        finally:
            # Remove the callback if it is still in the list. This will remove the
            #   callback if the execution is interrupted with Ctrl-C (in IPython).
            async with self._status_get_cb_lock:
                try:
                    n = self._wait_cb.index(cb)
                    self._wait_cb.pop(n)
                except Exception:
                    pass

        # Attempt to load the updated status
        try:
            await self._status(reload=True)
        except Exception:
            pass

        if timeout_occurred:
            raise self.WaitTimeoutError("Timeout while waiting for condition")
        if wait_cancelled:
            raise self.WaitCancelError("Wait for condition was cancelled")

    async def _status(self, *, reload=False):
        """
        Load status of RE Manager. The function returns status or raises exception if
        operation failed (e.g. timeout occurred). This is not part of API.

        The function is thread-safe. It is assumed that status may be simultaneously
        requested from multiple threads. The mechanism for loading and updating
        status information is designed to reuse previously loaded data whenever possible
        prevents communication channel and the server from overload in case
        many requests are sent in rapid sequence.

        Parameters
        ----------
        reload: boolean
            Immediately reload status (``True``) or return cached status if it
            is not expired (``False``).

        Returns
        -------
        dict
            Reference to the dictionary with RE Manager status

        Raises
        ------
            Reraises the exceptions raised by ``send_request`` API.
        """
        _status, _ex = None, None
        event = asyncio.Event()

        def cb(status, ex):
            nonlocal _status, _ex
            _status, _ex = status, ex
            event.set()

        async with self._status_get_cb_lock:
            self._status_get_cb.append(cb)
            if reload:
                self._status_timestamp = None
            self._event_status_get.set()

        await event.wait()
        if _ex:
            raise _ex
        else:
            return _status

    # =====================================================================================
    #                 API for monitoring and control of RE Manager

    async def status(self, *, reload=False):
        """Return the current status of RE Manager (cached unless ``reload`` is True)."""
        status = await self._status(reload=reload)
        return copy.deepcopy(status)  # Returns copy

    async def ping(self, *, reload=False):
        """Ping RE Manager (returns status; identical to ``status``)."""
        return await self.status(reload=reload)

    async def config_get(self):
        """Return config info for RE Manager."""
        return await self.send_request(method="config_get")

    async def wait_for_condition(self, condition, *, timeout=default_wait_timeout, monitor=None):
        """Wait for RE Manager status to satisfy an arbitrary ``condition`` callable."""
        await self._wait_for_condition(condition=condition, timeout=timeout, monitor=monitor)

    async def wait_for_idle(self, *, timeout=default_wait_timeout, monitor=None):
        """Wait for RE Manager to switch to the 'idle' state."""

        def condition(status):
            return status["manager_state"] == "idle"

        await self._wait_for_condition(condition=condition, timeout=timeout, monitor=monitor)

    async def wait_for_idle_or_paused(self, *, timeout=default_wait_timeout, monitor=None):
        """Wait for RE Manager to switch to the 'idle' or 'paused' state."""
        def condition(status):
            return status["manager_state"] in ("paused", "idle")

        await self._wait_for_condition(condition=condition, timeout=timeout, monitor=monitor)

    async def wait_for_idle_or_running(self, *, timeout=default_wait_timeout, monitor=None):
        """Wait for RE Manager to switch to the 'idle' or 'executing_queue' state."""
        def condition(status):
            return status["manager_state"] in ("executing_queue", "idle")

        await self._wait_for_condition(condition=condition, timeout=timeout, monitor=monitor)

    # =====================================================================================
    #                 API for monitoring and control of Queue

    async def item_add(
        self, item, *, pos=None, before_uid=None, after_uid=None, user=None, user_group=None, lock_key=None
    ):
        """Add an item (plan, instruction) to the queue."""
        request_params = self._prepare_item_add(
            item=item,
            pos=pos,
            before_uid=before_uid,
            after_uid=after_uid,
            user=user,
            user_group=user_group,
            lock_key=lock_key,
        )
        self._clear_status_timestamp()
        return await self.send_request(method="queue_item_add", params=request_params)

    async def item_add_batch(
        self, items, *, pos=None, before_uid=None, after_uid=None, user=None, user_group=None, lock_key=None
    ):
        """Add a batch of items to the queue."""
        request_params = self._prepare_item_add_batch(
            items=items,
            pos=pos,
            before_uid=before_uid,
            after_uid=after_uid,
            user=user,
            user_group=user_group,
            lock_key=lock_key,
        )
        self._clear_status_timestamp()
        return await self.send_request(method="queue_item_add_batch", params=request_params)

    async def item_update(self, item, *, replace=None, user=None, user_group=None, lock_key=None):
        """Update an existing item in the queue."""
        request_params = self._prepare_item_update(
            item=item, replace=replace, user=user, user_group=user_group, lock_key=lock_key
        )
        self._clear_status_timestamp()
        return await self.send_request(method="queue_item_update", params=request_params)

    async def item_remove(self, *, pos=None, uid=None, lock_key=None):
        """Remove an item from the queue."""
        request_params = self._prepare_item_remove(pos=pos, uid=uid, lock_key=lock_key)
        self._clear_status_timestamp()
        return await self.send_request(method="queue_item_remove", params=request_params)

    async def item_remove_batch(self, *, uids, ignore_missing=None, lock_key=None):
        """Remove a batch of items from the queue."""
        request_params = self._prepare_item_remove_batch(
            uids=uids, ignore_missing=ignore_missing, lock_key=lock_key
        )
        self._clear_status_timestamp()
        return await self.send_request(method="queue_item_remove_batch", params=request_params)

    async def item_move(
        self, *, pos=None, uid=None, pos_dest=None, before_uid=None, after_uid=None, lock_key=None
    ):
        """Move an item to a different position in the queue."""
        request_params = self._prepare_item_move(
            pos=pos, uid=uid, pos_dest=pos_dest, before_uid=before_uid, after_uid=after_uid, lock_key=lock_key
        )
        self._clear_status_timestamp()
        return await self.send_request(method="queue_item_move", params=request_params)

    async def item_move_batch(
        self, *, uids=None, pos_dest=None, before_uid=None, after_uid=None, reorder=None, lock_key=None
    ):
        """Move a batch of items to a different position in the queue."""
        request_params = self._prepare_item_move_batch(
            uids=uids,
            pos_dest=pos_dest,
            before_uid=before_uid,
            after_uid=after_uid,
            reorder=reorder,
            lock_key=lock_key,
        )
        self._clear_status_timestamp()
        return await self.send_request(method="queue_item_move_batch", params=request_params)

    async def item_get(self, *, pos=None, uid=None):
        """Load an item from the queue."""
        request_params = self._prepare_item_get(pos=pos, uid=uid)
        return await self.send_request(method="queue_item_get", params=request_params)

    async def item_execute(self, item, *, user=None, user_group=None, lock_key=None):
        """Immediately execute a single item (plan or instruction)."""
        request_params = self._prepare_item_execute(item=item, user=user, user_group=user_group, lock_key=lock_key)
        self._clear_status_timestamp()
        return await self.send_request(method="queue_item_execute", params=request_params)

    async def environment_open(self, *, lock_key=None):
        """Open RE Worker environment."""
        self._clear_status_timestamp()
        request_params = self._prepare_environment_control(lock_key=lock_key)
        return await self.send_request(method="environment_open", params=request_params)

    async def environment_close(self, *, lock_key=None):
        """Close RE Worker environment."""
        self._clear_status_timestamp()
        request_params = self._prepare_environment_control(lock_key=lock_key)
        return await self.send_request(method="environment_close", params=request_params)

    async def environment_destroy(self, *, lock_key=None):
        """Destroy RE Worker environment (kills the worker process)."""
        self._clear_status_timestamp()
        request_params = self._prepare_environment_control(lock_key=lock_key)
        return await self.send_request(method="environment_destroy", params=request_params)

    async def environment_update(self, *, run_in_background=None, lock_key=None):
        """Update cached lists of existing/allowed plans and devices in the worker environment."""
        self._clear_status_timestamp()
        request_params = self._prepare_environment_update(run_in_background=run_in_background, lock_key=lock_key)
        return await self.send_request(method="environment_update", params=request_params)

    async def queue_start(self, *, lock_key=None):
        """Start execution of the queue."""
        self._clear_status_timestamp()
        request_params = self._prepare_environment_control(lock_key=lock_key)
        return await self.send_request(method="queue_start", params=request_params)

    async def queue_stop(self, *, lock_key=None):
        """Request RE Manager to stop the queue after the currently running plan."""
        self._clear_status_timestamp()
        request_params = self._prepare_environment_control(lock_key=lock_key)
        return await self.send_request(method="queue_stop", params=request_params)

    async def queue_stop_cancel(self, *, lock_key=None):
        """Cancel the pending request to stop the queue."""
        self._clear_status_timestamp()
        request_params = self._prepare_environment_control(lock_key=lock_key)
        return await self.send_request(method="queue_stop_cancel", params=request_params)

    async def queue_clear(self, *, lock_key=None):
        """Remove all items from the queue."""
        self._clear_status_timestamp()
        request_params = self._prepare_queue_clear(lock_key=lock_key)
        return await self.send_request(method="queue_clear", params=request_params)

    async def queue_autostart(self, enable, *, lock_key=None):
        """Enable or disable autostart mode."""
        request_params = self._prepare_queue_autostart(enable=enable, lock_key=lock_key)
        self._clear_status_timestamp()
        return await self.send_request(method="queue_autostart", params=request_params)

    async def queue_mode_set(self, **kwargs):
        """Set parameters of the queue mode (e.g. ``loop``, ``ignore_failures``)."""
        request_params = self._prepare_queue_mode_set(**kwargs)
        self._clear_status_timestamp()
        return await self.send_request(method="queue_mode_set", params=request_params)

    async def queue_get(self, *, reload=False):
        """Return the list of queue items and the currently running item (cached by UID)."""
        status = await self._status(reload=reload)
        plan_queue_uid = status["plan_queue_uid"]
        if plan_queue_uid != self._current_plan_queue_uid:
            response = await self.send_request(method="queue_get")
            self._process_response_queue_get(response)
        else:
            response = self._generate_response_queue_get()
        return response

    async def history_get(self, *, reload=False):
        """Return the list of history items (cached by UID)."""
        status = await self._status(reload=reload)
        plan_history_uid = status["plan_history_uid"]
        if plan_history_uid != self._current_plan_history_uid:
            response = await self.send_request(method="history_get")
            self._process_response_history_get(response)
        else:
            response = self._generate_response_history_get()
        return response

    async def history_clear(self, *, size=None, item_uid=None, lock_key=None):
        """Remove all items from the history."""
        self._clear_status_timestamp()
        request_params = self._prepare_history_clear(size=size, item_uid=item_uid, lock_key=lock_key)
        return await self.send_request(method="history_clear", params=request_params)

    async def plans_allowed(self, *, reload=False, user_group=None):
        """Return the dictionary of allowed plans for a user group (cached by UID)."""
        status = await self._status(reload=reload)
        plans_allowed_uid = status["plans_allowed_uid"]
        user_group = self._get_user_group_for_allowed_plans_devices(user_group=user_group)
        if (plans_allowed_uid != self._current_plans_allowed_uid) or (
            user_group not in self._current_plans_allowed
        ):
            request_params = self._prepare_plans_devices_allowed(user_group=user_group)
            response = await self.send_request(method="plans_allowed", params=request_params)
            self._process_response_plans_allowed(response, user_group=user_group)
        else:
            response = self._generate_response_plans_allowed(user_group=user_group)
        return response

    async def devices_allowed(self, *, reload=False, user_group=None):
        """Return the dictionary of allowed devices for a user group (cached by UID)."""
        status = await self._status(reload=reload)
        devices_allowed_uid = status["devices_allowed_uid"]
        user_group = self._get_user_group_for_allowed_plans_devices(user_group=user_group)
        if (devices_allowed_uid != self._current_devices_allowed_uid) or (
            user_group not in self._current_devices_allowed
        ):
            request_params = self._prepare_plans_devices_allowed(user_group=user_group)
            response = await self.send_request(method="devices_allowed", params=request_params)
            self._process_response_devices_allowed(response, user_group=user_group)
        else:
            response = self._generate_response_devices_allowed(user_group=user_group)
        return response

    async def plans_existing(self, *, reload=False):
        """Return the dictionary of existing plans in the worker namespace (cached by UID)."""
        status = await self._status(reload=reload)
        plans_existing_uid = status["plans_existing_uid"]
        if plans_existing_uid != self._current_plans_existing_uid:
            response = await self.send_request(method="plans_existing")
            self._process_response_plans_existing(response)
        else:
            response = self._generate_response_plans_existing()
        return response

    async def devices_existing(self, *, reload=False):
        """Return the dictionary of existing devices in the worker namespace (cached by UID)."""
        status = await self._status(reload=reload)
        devices_existing_uid = status["devices_existing_uid"]
        if devices_existing_uid != self._current_devices_existing_uid:
            response = await self.send_request(method="devices_existing")
            self._process_response_devices_existing(response)
        else:
            response = self._generate_response_devices_existing()
        return response

    async def permissions_reload(self, *, restore_plans_devices=None, restore_permissions=None, lock_key=None):
        """Reload user group permissions from disk and generate lists of allowed plans/devices."""
        request_params = self._prepare_permissions_reload(
            restore_plans_devices=restore_plans_devices,
            restore_permissions=restore_permissions,
            lock_key=lock_key,
        )
        self._clear_status_timestamp()
        return await self.send_request(method="permissions_reload", params=request_params)

    async def permissions_get(self):
        """Return the dictionary of user group permissions."""
        return await self.send_request(method="permissions_get")

    async def permissions_set(self, user_group_permissions, *, lock_key=None):
        """Upload the dictionary of user group permissions."""
        request_params = self._prepare_permissions_set(
            user_group_permissions=user_group_permissions, lock_key=lock_key
        )
        self._clear_status_timestamp()
        return await self.send_request(method="permissions_set", params=request_params)

    async def script_upload(
        self, script, *, update_lists=None, update_re=None, run_in_background=None, lock_key=None
    ):
        """Upload and execute a script in the RE Worker namespace."""
        request_params = self._prepare_script_upload(
            script=script,
            update_lists=update_lists,
            update_re=update_re,
            run_in_background=run_in_background,
            lock_key=lock_key,
        )
        self._clear_status_timestamp()
        return await self.send_request(method="script_upload", params=request_params)

    async def function_execute(self, item, *, run_in_background=None, user=None, user_group=None, lock_key=None):
        """Start execution of a function in the RE Worker namespace."""
        request_params = self._prepare_function_execute(
            item=item, run_in_background=run_in_background, user=user, user_group=user_group, lock_key=lock_key
        )
        self._clear_status_timestamp()
        return await self.send_request(method="function_execute", params=request_params)

    async def task_status(self, task_uid):
        """Return the status of one or more background tasks."""
        request_params = self._prepare_task_status(task_uid=task_uid)
        self._clear_status_timestamp()
        return await self.send_request(method="task_status", params=request_params)

    async def task_result(self, task_uid):
        """Return the status and result of a background task."""
        request_params = self._prepare_task_result(task_uid=task_uid)
        self._clear_status_timestamp()
        return await self.send_request(method="task_result", params=request_params)

    async def _wait_for_task_results_update(
        self, task_results_uid, *, timeout=default_wait_timeout, monitor=None, reset_time_start=True
    ):
        """
        Wait for ``task_results_uid`` to change in RE Manager status.
        """
        new_task_results_uid = task_results_uid

        if not monitor:
            reset_time_start = True
            monitor = WaitMonitor()
        if reset_time_start:
            monitor._time_start = ttime.time()
        monitor.set_timeout(timeout)

        def condition(status):
            nonlocal new_task_results_uid
            new_task_results_uid = status["task_results_uid"]
            return new_task_results_uid != task_results_uid

        await self._wait_for_condition(
            condition=condition, timeout=timeout, monitor=monitor, reset_time_start=False
        )

    async def wait_for_completed_task(
        self, task_uid, *, timeout=default_wait_timeout, monitor=None, treat_not_found_as_completed=True
    ):
        """Wait for one or more background tasks to complete."""
        task_uid = self._prepare_wait_for_completed_task(task_uid=task_uid)

        monitor = monitor or WaitMonitor()
        monitor._time_start = ttime.time()
        monitor.set_timeout(timeout)

        async def detect_completed_tasks():
            task_status_reply = await self.task_status(task_uid=task_uid)
            completed_tasks = self._pick_completed_tasks(
                task_status_reply, treat_not_found_as_completed=treat_not_found_as_completed
            )
            return completed_tasks

        current_task_results_uid = (await self.status())["task_results_uid"]

        completed_tasks = await detect_completed_tasks()
        if completed_tasks:
            return completed_tasks

        while True:
            # Loop until the 'wait' function is timed out or cancelled or until
            #   some tasks are completed.
            await self._wait_for_task_results_update(
                current_task_results_uid,
                timeout=timeout,
                monitor=monitor,
                reset_time_start=False,
            )
            completed_tasks = await detect_completed_tasks()
            if completed_tasks:
                return completed_tasks

    async def re_runs(self, option=None, *, reload=False):
        """Return the list of runs of the currently executed plan (cached by UID)."""
        self._verify_options_re_runs(option=option)
        status = await self._status(reload=reload)
        run_list_uid = status["run_list_uid"]
        if run_list_uid != self._current_run_list_uid:
            response = await self.send_request(method="re_runs")
            response = self._process_response_re_runs(response, option=option)
        else:
            response = self._generate_response_re_runs(option=option)
        return response

    async def re_pause(self, option=None, *, lock_key=None):
        """Request Run Engine to pause the currently running plan."""
        request_params = self._prepare_re_pause(option=option, lock_key=lock_key)
        self._clear_status_timestamp()
        return await self.send_request(method="re_pause", params=request_params)

    async def re_resume(self, *, lock_key=None):
        """Request Run Engine to resume the paused plan."""
        self._clear_status_timestamp()
        request_params = self._prepare_environment_control(lock_key=lock_key)
        return await self.send_request(method="re_resume", params=request_params)

    async def re_stop(self, *, lock_key=None):
        """Request Run Engine to stop the paused plan."""
        self._clear_status_timestamp()
        request_params = self._prepare_environment_control(lock_key=lock_key)
        return await self.send_request(method="re_stop", params=request_params)

    async def re_abort(self, *, lock_key=None):
        """Request Run Engine to abort the paused plan."""
        self._clear_status_timestamp()
        request_params = self._prepare_environment_control(lock_key=lock_key)
        return await self.send_request(method="re_abort", params=request_params)

    async def re_halt(self, *, lock_key=None):
        """Request Run Engine to halt the paused plan."""
        self._clear_status_timestamp()
        request_params = self._prepare_environment_control(lock_key=lock_key)
        return await self.send_request(method="re_halt", params=request_params)

    async def re_metadata(self):
        """Return Run Engine metadata."""
        return await self.send_request(method="re_metadata")

    async def lock(self, lock_key=None, *, environment=None, queue=None, note=None, user=None):
        """Lock RE Manager environment and/or queue with a lock key."""
        request_params = self._prepare_lock(
            environment=environment, queue=queue, lock_key=lock_key, note=note, user=user
        )
        self._clear_status_timestamp()
        return await self.send_request(method="lock", params=request_params)

    async def lock_environment(self, lock_key=None, *, note=None, user=None):
        """Lock the RE Manager environment."""
        return await self.lock(lock_key=lock_key, environment=True, note=note, user=user)

    async def lock_queue(self, lock_key=None, *, note=None, user=None):
        """Lock the RE Manager queue."""
        return await self.lock(lock_key=lock_key, queue=True, note=note, user=user)

    async def lock_all(self, lock_key=None, *, note=None, user=None):
        """Lock both the RE Manager environment and queue."""
        return await self.lock(lock_key=lock_key, environment=True, queue=True, note=note, user=user)

    async def lock_info(self, lock_key=None, *, reload=False):
        """Return the lock status of RE Manager (cached by UID) and optionally validate a lock key."""
        status = await self._status(reload=reload)
        lock_info_uid = status["lock_info_uid"]
        if (lock_info_uid != self._current_lock_info_uid) or (lock_key is not None):
            request_params = self._prepare_lock_info(lock_key=lock_key)
            response = await self.send_request(method="lock_info", params=request_params)
            self._process_response_lock_info(response)
        else:
            response = self._generate_response_lock_info()
        return response

    async def unlock(self, lock_key=None):
        """Unlock RE Manager with the lock key."""
        request_params = self._prepare_unlock(lock_key=lock_key)
        self._clear_status_timestamp()
        return await self.send_request(method="unlock", params=request_params)

    async def kernel_interrupt(self, *, interrupt_task=None, interrupt_plan=None, lock_key=None):
        """Send an interrupt request to the IPython kernel."""
        request_params = self._prepare_kernel_interrupt(
            interrupt_task=interrupt_task, interrupt_plan=interrupt_plan, lock_key=lock_key
        )
        self._clear_status_timestamp()
        return await self.send_request(method="kernel_interrupt", params=request_params)
