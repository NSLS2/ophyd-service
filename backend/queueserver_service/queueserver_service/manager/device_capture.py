"""
Capture device constructor calls at instantiation time.

While a capture window is open, every construction of an ophyd
(``OphydObject`` subclass) or ophyd-async (``Device`` subclass) object is
recorded with the exact ``(class, args, kwargs)`` of the call — so
``EpicsMotor('XF:31ID-ED{Mtr}', name='mtr')`` yields a faithful
instantiation spec instead of one reconstructed from the finished object.
:func:`build_instantiation_specs` then selects the records that correspond
to top-level namespace devices and falls back to
:func:`~.device_introspection.device_to_instantiation_spec` for anything
constructed outside the window (or through a class-specific ``__new__``
the interception cannot see).

Mechanism: ``Class(*args, **kwargs)`` resolves through
``type.__call__`` → ``Class.__new__(Class, *args, **kwargs)`` before
``__init__`` runs, so a ``__new__`` dispatcher on the framework base class
observes the original call of every subclass that does not define its own
``__new__``. The dispatcher is installed ONCE per process and stays
installed; opening a window only points it at a recording sink, and closing
the window detaches the sink. Deleting a ``__new__`` assigned to a base
class is NOT a clean restore in CPython — after ``del``, subclasses lose
``object.__new__``'s excess-argument exemption and plain construction like
``Signal(name=...)`` raises TypeError — so, like ophyd's own append-only
instantiation-callback list, the patch is permanent and inert when no
window is open. When inactive (and for ophyd-async, always) the dispatcher
reproduces the original construction semantics exactly. The recording step
never raises — a failing record lands in ``DeviceCapture.diagnostics``
rather than breaking device construction.

The emitted file (:func:`write_happi_json`) is a happi-format JSON database
(one dict keyed by device name, ``OphydItem``-shaped entries) readable by
bluesky-configuration-service's happi seed strategy and by real happi
tooling. No happi package is involved on either side. Entries that could
not be captured portably — constructor arguments that don't survive JSON,
or classes defined in the startup script itself — are emitted with
``active: false`` and an explanatory ``documentation`` note, because the
config-service loader skips inactive entries harmlessly but refuses the
whole file on a single malformed one.
"""

from __future__ import annotations

import contextlib
import importlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .device_introspection import device_to_instantiation_spec

logger = logging.getLogger(__name__)

# Framework tags use direct_control's vocabulary (drivers.FRAMEWORK_SYNC/_ASYNC);
# the registry consumer hard-fails on any other value, so never invent tags here.
FRAMEWORK_SYNC = "ophyd-sync"
FRAMEWORK_ASYNC = "ophyd-async"

HAPPI_DB_FILE_NAME = "happi_db.json"

# The active recording sink, or None when no window is open. The __new__
# dispatchers below read it on every construction; toggling it is the whole
# enable/disable mechanism (the dispatchers themselves are never removed).
_sink: Optional["DeviceCapture"] = None
_ophyd_state: Optional[str] = None  # None (not attempted) / "installed" / "disabled"
_async_state: Optional[str] = None


@dataclass
class DeviceCapture:
    """Constructor calls observed during one capture window."""

    # id(instance) -> (class, args, kwargs, framework tag)
    records: Dict[int, Tuple[type, tuple, dict, str]] = field(default_factory=dict)
    # Human-readable notes about anything the window could not record.
    diagnostics: List[str] = field(default_factory=list)


def _record(obj: Any, cls: type, args: tuple, kwargs: dict, framework: str) -> None:
    sink = _sink
    if sink is not None:
        try:
            sink.records[id(obj)] = (cls, args, kwargs, framework)
        except Exception as exc:  # pragma: no cover - defensive
            sink.diagnostics.append(f"failed to record {cls!r}: {exc}")


def _install_ophyd_dispatcher() -> str:
    try:
        from ophyd.ophydobj import OphydObject
    except ImportError:
        return "disabled: ophyd is not importable"

    if "__new__" in vars(OphydObject):
        # A future ophyd defining its own __new__ must not be clobbered.
        return "disabled: ophyd OphydObject defines its own __new__"

    def _ophyd_new(cls, *args, **kwargs):
        # Reproduces object.__new__'s excess-argument exemption (every
        # OphydObject subclass overrides __init__), so behavior with no
        # sink attached is identical to unpatched ophyd.
        orig = super(OphydObject, cls).__new__
        obj = orig(cls) if orig is object.__new__ else orig(cls, *args, **kwargs)
        _record(obj, cls, args, kwargs, FRAMEWORK_SYNC)
        return obj

    OphydObject.__new__ = _ophyd_new
    return "installed"


def _install_async_dispatcher() -> str:
    try:
        from ophyd_async.core import Device as _AsyncDevice
    except ImportError:
        # ophyd-async is an optional dependency; its absence is normal.
        return "disabled: ophyd-async is not importable"

    # ophyd-async Device.__new__ does real work (it installs
    # _setattr_methods before any __setattr__ runs) — delegate to it.
    orig_async_new = _AsyncDevice.__new__

    def _async_new(cls, *args, **kwargs):
        if orig_async_new is object.__new__:  # pragma: no cover - defensive
            obj = object.__new__(cls)
        else:
            obj = orig_async_new(cls, *args, **kwargs)
        _record(obj, cls, args, kwargs, FRAMEWORK_ASYNC)
        return obj

    _AsyncDevice.__new__ = _async_new
    return "installed"


@contextlib.contextmanager
def capture_device_instantiations():
    """
    Context manager opening a capture window. Yields a :class:`DeviceCapture`.

    Reentrant use is an error: the recording sink is process-global, and two
    overlapping windows could not be separated.
    """
    global _sink, _ophyd_state, _async_state
    if _sink is not None:
        raise RuntimeError("Device instantiation capture is already active in this process")

    if _ophyd_state is None:
        _ophyd_state = _install_ophyd_dispatcher()
    if _async_state is None:
        _async_state = _install_async_dispatcher()

    capture = DeviceCapture()
    for state, label in ((_ophyd_state, "ophyd"), (_async_state, "ophyd-async")):
        if state != "installed":
            capture.diagnostics.append(f"{label} capture {state}")

    _sink = capture
    try:
        yield capture
    finally:
        _sink = None


def _class_import_path(cls: type) -> str:
    return f"{cls.__module__}.{cls.__name__}"


def _class_is_importable(cls: type) -> bool:
    """
    True if ``cls`` can be re-imported from its dotted path in another
    process. Startup scripts execute with ``__name__ == '__main__'``, so
    classes defined in the profile itself fail this check.
    """
    module_name = cls.__module__
    if module_name in ("__main__", "builtins"):
        return False
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return False
    return getattr(module, cls.__name__, None) is cls


def _sanitize_value(value: Any, device_names_by_id: Dict[int, str], notes: List[str], where: str) -> Any:
    """
    Convert one args/kwargs value to a JSON-serializable form. A device
    reference becomes its namespace name; anything else non-serializable
    becomes its repr. Either substitution appends a note, which demotes the
    entry to ``active: false`` — a string is not the object the constructor
    originally received, so the spec must not claim to be runnable as-is.
    """
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(v, device_names_by_id, notes, where) for v in value]
    if isinstance(value, dict):
        return {
            str(k): _sanitize_value(v, device_names_by_id, notes, f"{where}[{k!r}]")
            for k, v in value.items()
        }
    device_name = device_names_by_id.get(id(value))
    if device_name is not None:
        notes.append(f"{where}: device reference replaced by its name {device_name!r}")
        return device_name
    notes.append(f"{where}: non-serializable value replaced by repr {value!r:.120}")
    return repr(value)


def build_instantiation_specs(
    devices_in_nspace: Dict[str, Any],
    capture: Optional[DeviceCapture] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Build ``{name: spec}`` for every top-level namespace device.

    A device with a captured constructor call gets the exact
    ``device_class``/``args``/``kwargs`` of that call; anything else falls
    back to introspection of the live instance
    (:func:`device_to_instantiation_spec`), noted in ``documentation``.
    Entries whose class cannot be re-imported elsewhere or whose arguments
    required substitution are demoted to ``active: false`` with a note —
    they are recorded, never silently runnable.
    """
    records = capture.records if capture is not None else {}
    device_names_by_id = {id(device): name for name, device in devices_in_nspace.items()}
    specs: Dict[str, Dict[str, Any]] = {}

    for name, device in devices_in_nspace.items():
        cls = type(device)
        notes: List[str] = []
        record = records.get(id(device))

        if record is not None:
            rec_cls, args, kwargs, framework = record
            cls = rec_cls
            spec = {
                "name": name,
                "device_class": _class_import_path(cls),
                "args": _sanitize_value(list(args), device_names_by_id, notes, "args"),
                "kwargs": _sanitize_value(dict(kwargs), device_names_by_id, notes, "kwargs"),
                "active": True,
            }
        else:
            try:
                spec = device_to_instantiation_spec(name, device)
            except Exception as exc:
                logger.warning("Device %r: introspection fallback failed: %s", name, exc)
                continue
            framework = _infer_framework(device)
            notes.append("spec reconstructed from the live instance (constructor call not captured)")

        if framework is not None:
            spec["framework"] = framework

        if not _class_is_importable(cls):
            notes.append(
                f"class {_class_import_path(cls)!r} is not importable outside the startup "
                f"script that defined it"
            )
        # Substitutions and importability problems make the spec non-runnable;
        # reconstruction alone does not.
        if any(not n.startswith("spec reconstructed") for n in notes):
            spec["active"] = False
        if notes:
            spec["documentation"] = "; ".join(notes)

        specs[name] = spec

    return specs


def _infer_framework(device: Any) -> Optional[str]:
    try:
        from ophyd.ophydobj import OphydObject

        if isinstance(device, OphydObject):
            return FRAMEWORK_SYNC
    except ImportError:
        pass
    try:
        from ophyd_async.core import Device as _AsyncDevice

        if isinstance(device, _AsyncDevice):
            return FRAMEWORK_ASYNC
    except ImportError:
        pass
    return None


def write_happi_json(specs: Dict[str, Dict[str, Any]], *, file_dir: str, file_name: str = HAPPI_DB_FILE_NAME) -> str:
    """
    Write the specs as a happi-format JSON database and return its path.

    The file is one JSON object keyed by device name, each entry shaped as
    a generic happi ``OphydItem`` plus the ``framework`` tag. The write is
    atomic (temp file + rename in the destination directory).
    """
    db: Dict[str, Dict[str, Any]] = {}
    for name, spec in specs.items():
        entry: Dict[str, Any] = {
            "_id": name,
            "name": name,
            "type": "OphydItem",
            "device_class": spec["device_class"],
            "args": spec.get("args", []),
            "kwargs": spec.get("kwargs", {}),
            "active": spec.get("active", True),
        }
        args = entry["args"]
        if args and isinstance(args[0], str) and ":" in args[0]:
            entry["prefix"] = args[0]
        for optional_key in ("framework", "documentation"):
            if spec.get(optional_key):
                entry[optional_key] = spec[optional_key]
        db[name] = entry

    path = os.path.join(file_dir, file_name)
    fd, tmp_path = tempfile.mkstemp(dir=file_dir, prefix=f".{file_name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(db, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise
    return path
