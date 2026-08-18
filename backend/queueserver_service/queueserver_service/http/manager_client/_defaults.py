# Ported from bluesky-queueserver-api (BSD-3), commit e3fb37f1 (v0.0.13 + 6 commits, 2026-04-07).
# Trimmed to the async 0MQ path; imports rewired to in-tree queueserver_service modules.

default_allow_request_fail_exceptions = True

default_status_expiration_period = 0.5  # s
default_status_polling_period = 1.0  # s

default_console_monitor_poll_timeout = 1.0  # s, 0MQ
default_console_monitor_max_msgs = 10000
default_console_monitor_max_lines = 1000

default_system_info_monitor_poll_timeout = 1.0  # s, 0MQ
default_system_info_monitor_max_msgs = 10000

default_zmq_request_timeout_recv = 2.0  # s
default_zmq_request_timeout_send = 0.5  # s

default_wait_timeout = 600  # Timeout for wait operations in seconds

default_user_name = "Queue Server API User"
default_user_group = "primary"
