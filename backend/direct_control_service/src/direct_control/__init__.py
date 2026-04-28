"""
Direct Device Control + Monitoring Service (SVC-003).

Device commanding with A4 coordination checks, plus real-time EPICS PV
monitoring via WebSocket.

Lazy imports: Settings and pyepics-dependent modules are loaded on first
access so CLI env vars are in place before pyepics reads them at import time.
"""

# Configures the dynamic-library search path for pyepics' bundled CA libs.
# Must run BEFORE any `from epics import ...` (otherwise epicscorelibs warns
# that the path setup arrived too late). Side-effect-only import, no API used.
import epicscorelibs.path.pyepics  # noqa: F401

from typing import Any

__version__ = "1.0.0"


_MODEL_NAMES = frozenset(
    {
        "PVSetRequest",
        "PVSetResponse",
        "DeviceCommandRequest",
        "DeviceCommandResponse",
        "CoordinationStatus",
        "DeviceLockStatus",
        "CommandMode",
        "ControlError",
        "DeviceLockedError",
        "CoordinationCheckError",
        "HealthResponse",
        "WebSocketAction",
        "WebSocketSetRequest",
        "WebSocketSetResponse",
        "WebSocketMessage",
        "NestedDeviceRequest",
        "NestedDeviceResponse",
        "PVLimits",
        "ValueLimitError",
        "PVValue",
        "PVUpdate",
        "PVInfo",
        "PVValueResponse",
        "PVMonitorRequest",
        "PVSubscription",
        "SubscriptionStatus",
        "DeviceUpdate",
        "DeviceInfo",
        "AlarmSeverity",
        "ALARM_SEVERITY_NAMES",
        "MonitoringError",
        "PVNotFoundError",
        "SubscriptionError",
        "StopRequest",
        "StopResponse",
    }
)


def __getattr__(name: str) -> Any:
    if name == "Settings":
        from .config import Settings

        return Settings

    if name == "CoordinationClient":
        from .coordination_client import CoordinationClient

        return CoordinationClient

    if name == "DeviceController":
        from .device_controller import DeviceController

        return DeviceController

    if name in _MODEL_NAMES:
        from . import models

        return getattr(models, name)

    if name == "app":
        from .main import app

        return app

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Settings",
    "CoordinationClient",
    "DeviceController",
    "app",
    # Control models
    "PVSetRequest",
    "PVSetResponse",
    "DeviceCommandRequest",
    "DeviceCommandResponse",
    "CoordinationStatus",
    "DeviceLockStatus",
    "CommandMode",
    "ControlError",
    "DeviceLockedError",
    "CoordinationCheckError",
    "HealthResponse",
    "WebSocketAction",
    "WebSocketSetRequest",
    "WebSocketSetResponse",
    "WebSocketMessage",
    "NestedDeviceRequest",
    "NestedDeviceResponse",
    "PVLimits",
    "ValueLimitError",
    "StopRequest",
    "StopResponse",
    # Monitoring models
    "PVValue",
    "PVUpdate",
    "PVInfo",
    "PVValueResponse",
    "PVMonitorRequest",
    "PVSubscription",
    "SubscriptionStatus",
    "DeviceUpdate",
    "DeviceInfo",
    "AlarmSeverity",
    "ALARM_SEVERITY_NAMES",
    "MonitoringError",
    "PVNotFoundError",
    "SubscriptionError",
]
