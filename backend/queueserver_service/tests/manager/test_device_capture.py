import json
import os

import ophyd
import ophyd.sim
import pytest

from queueserver_service.manager.device_capture import (
    FRAMEWORK_SYNC,
    build_instantiation_specs,
    capture_device_instantiations,
    write_happi_json,
)
from queueserver_service.manager.device_introspection import instantiate_device_from_spec
from queueserver_service.manager.profile_ops import devices_from_nspace, load_worker_startup_code

# fmt: off
_startup_script_capture = """
from ophyd import Signal
from ophyd.sim import SynAxis

sig1 = Signal(name="sig1", value=42)
motor1 = SynAxis(name="motor1")

class LocalDevice(Signal):
    pass

local_dev = LocalDevice(name="local_dev")
"""
# fmt: on


def test_capture_exact_args_01():
    """Exact constructor args are recorded, including for classes that are not importable."""
    fake_motor_cls = ophyd.sim.make_fake_device(ophyd.EpicsMotor)
    with capture_device_instantiations() as capture:
        motor = fake_motor_cls("XF:31ID-ED{Mtr}", name="mtr")
        sig = ophyd.Signal(name="sig1", value=42)

    specs = build_instantiation_specs({"mtr": motor, "sig1": sig}, capture)

    assert set(specs) == {"mtr", "sig1"}
    spec_mtr = specs["mtr"]
    assert spec_mtr["args"] == ["XF:31ID-ED{Mtr}"]
    assert spec_mtr["kwargs"] == {"name": "mtr"}
    assert spec_mtr["framework"] == FRAMEWORK_SYNC
    # make_fake_device() classes are synthesized and can not be re-imported.
    assert spec_mtr["active"] is False
    assert "not importable" in spec_mtr["documentation"]

    spec_sig = specs["sig1"]
    assert spec_sig["device_class"] == "ophyd.signal.Signal"
    assert spec_sig["args"] == []
    assert spec_sig["kwargs"] == {"name": "sig1", "value": 42}
    assert spec_sig["active"] is True
    assert "documentation" not in spec_sig


def test_capture_exact_args_02():
    """Child signals created inside a compound device do not leak into the specs."""
    with capture_device_instantiations() as capture:
        motor = ophyd.sim.SynAxis(name="motor1")

    assert len(capture.records) > 1  # children were recorded ...
    specs = build_instantiation_specs({"motor1": motor}, capture)
    assert set(specs) == {"motor1"}  # ... but only the namespace device is emitted
    assert specs["motor1"]["device_class"] == "ophyd.sim.SynAxis"
    assert specs["motor1"]["kwargs"]["name"] == "motor1"
    assert specs["motor1"]["active"] is True


def test_capture_fallback_reconstruction_01():
    """A device constructed outside the window falls back to introspection."""
    sig = ophyd.Signal(name="sig1")
    with capture_device_instantiations() as capture:
        pass

    specs = build_instantiation_specs({"sig1": sig}, capture)
    spec = specs["sig1"]
    assert spec["device_class"] == "ophyd.signal.Signal"
    assert spec["active"] is True
    assert "reconstructed" in spec["documentation"]


def test_capture_nonserializable_args_01():
    """Non-JSON-serializable constructor arguments demote the entry to inactive."""
    with capture_device_instantiations() as capture:
        sig = ophyd.sim.SynSignal(func=lambda: 1, name="sig1")

    specs = build_instantiation_specs({"sig1": sig}, capture)
    spec = specs["sig1"]
    assert spec["active"] is False
    assert "non-serializable" in spec["documentation"]
    json.dumps(spec)  # the emitted form must still be serializable


def test_capture_device_reference_arg_01():
    """A device passed as a constructor argument is replaced by its name and demotes the entry."""
    with capture_device_instantiations() as capture:
        parent = ophyd.sim.SynAxis(name="parent_dev")
        child = ophyd.Signal(name="child_sig", parent=parent)

    specs = build_instantiation_specs({"parent_dev": parent, "child_sig": child}, capture)
    spec = specs["child_sig"]
    assert spec["kwargs"]["parent"] == "parent_dev"
    assert spec["active"] is False
    assert "device reference" in spec["documentation"]


def test_capture_deactivation_01():
    """Recording stops when the window closes — on normal exit and on exception."""
    with capture_device_instantiations() as capture:
        ophyd.Signal(name="sig_in")
    n_records = len(capture.records)
    assert n_records > 0

    # Construction outside the window works and is not recorded.
    sig = ophyd.Signal(name="sig_out")
    assert sig.name == "sig_out"
    assert len(capture.records) == n_records

    with pytest.raises(RuntimeError, match="boom"):
        with capture_device_instantiations() as capture2:
            raise RuntimeError("boom")
    sig2 = ophyd.Signal(name="sig_after_error")
    assert sig2.name == "sig_after_error"
    assert len(capture2.records) == 0


def test_capture_reentrancy_guard_01():
    """Opening a second capture window inside the first is an error."""
    with capture_device_instantiations() as capture:
        with pytest.raises(RuntimeError, match="already active"):
            with capture_device_instantiations():
                pass
        # The failed inner attempt must not have detached the outer sink.
        ophyd.Signal(name="sig_outer")
        assert len(capture.records) > 0


def test_capture_via_startup_code_01(tmp_path):
    """End-to-end through load_worker_startup_code: capture, select, emit, reload."""
    script_dir = os.path.join(tmp_path, "script_dir1")
    os.makedirs(script_dir, exist_ok=True)
    with open(os.path.join(script_dir, "startup_script.py"), "w") as f:
        f.write(_startup_script_capture)

    with capture_device_instantiations() as capture:
        nspace = load_worker_startup_code(
            startup_script_path=os.path.join(script_dir, "startup_script.py")
        )
    devices = devices_from_nspace(nspace)
    specs = build_instantiation_specs(devices, capture)

    assert {"sig1", "motor1", "local_dev"} <= set(specs)

    assert specs["sig1"]["kwargs"] == {"name": "sig1", "value": 42}
    assert specs["sig1"]["active"] is True
    assert specs["motor1"]["device_class"] == "ophyd.sim.SynAxis"
    assert specs["motor1"]["active"] is True
    # Classes defined in the startup script itself are recorded but inactive.
    assert specs["local_dev"]["active"] is False
    assert "not importable" in specs["local_dev"]["documentation"]

    path = write_happi_json(specs, file_dir=str(tmp_path))
    with open(path) as f:
        db = json.load(f)

    entry = db["sig1"]
    assert entry["_id"] == "sig1"
    assert entry["name"] == "sig1"
    assert entry["type"] == "OphydItem"
    assert entry["device_class"] == "ophyd.signal.Signal"
    assert entry["framework"] == FRAMEWORK_SYNC
    assert entry["active"] is True

    # An active entry must instantiate back into a live device.
    device = instantiate_device_from_spec(db["motor1"])
    assert device.name == "motor1"


def test_write_happi_json_01(tmp_path):
    """Entry shape details: prefix derivation and inactive entries."""
    specs = {
        "mtr": {
            "name": "mtr",
            "device_class": "ophyd.EpicsMotor",
            "args": ["XF:31ID-ED{Mtr}"],
            "kwargs": {"name": "mtr"},
            "active": True,
            "framework": FRAMEWORK_SYNC,
        },
        "broken": {
            "name": "broken",
            "device_class": "__main__.LocalDevice",
            "args": [],
            "kwargs": {"name": "broken"},
            "active": False,
            "documentation": "class not importable",
        },
    }
    path = write_happi_json(specs, file_dir=str(tmp_path))
    assert os.path.basename(path) == "happi_db.json"
    with open(path) as f:
        db = json.load(f)

    assert db["mtr"]["prefix"] == "XF:31ID-ED{Mtr}"
    assert "prefix" not in db["broken"]
    assert db["broken"]["active"] is False
    assert db["broken"]["documentation"] == "class not importable"
    assert "framework" not in db["broken"]
