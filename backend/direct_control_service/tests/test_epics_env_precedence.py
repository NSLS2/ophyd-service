"""
EPICS env-var precedence in the PV monitor module.

pv_monitor sets EPICS_CA_* before importing ophyd/pyepics. The contract:
the DIRECT_CONTROL_-prefixed variables are explicit overrides only — a
deployment that sets the bare EPICS_CA_* variables (as every pod compose
does) must see them honored, and when nothing is set at all, libca's own
defaults apply. Regression for the silent override where an unset
DIRECT_CONTROL_EPICS_CA_AUTO_ADDR_LIST defaulted to "YES" and clobbered
an explicit EPICS_CA_AUTO_ADDR_LIST=NO.

The logic runs at module import, so each case imports the module in a
fresh subprocess with a controlled environment.
"""

import os
import subprocess
import sys

_PROBE = (
    "import os, json;"
    "import direct_control.monitoring.pv_monitor;"
    "print(json.dumps({"
    "'addr': os.environ.get('EPICS_CA_ADDR_LIST'),"
    "'auto': os.environ.get('EPICS_CA_AUTO_ADDR_LIST')}))"
)

_VARS = (
    "EPICS_CA_ADDR_LIST",
    "EPICS_CA_AUTO_ADDR_LIST",
    "DIRECT_CONTROL_EPICS_CA_ADDR_LIST",
    "DIRECT_CONTROL_EPICS_CA_AUTO_ADDR_LIST",
)


def _import_with(env_overrides: dict) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _VARS}
    env.update(env_overrides)
    out = subprocess.run(
        [sys.executable, "-c", _PROBE],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    import json

    return json.loads(out.stdout.strip().splitlines()[-1])


def test_bare_auto_addr_list_is_honored():
    """An explicit EPICS_CA_AUTO_ADDR_LIST=NO survives the import untouched."""
    result = _import_with({"EPICS_CA_AUTO_ADDR_LIST": "NO"})
    assert result["auto"] == "NO"


def test_bare_addr_list_is_honored():
    result = _import_with({"EPICS_CA_ADDR_LIST": "10.0.0.1 10.0.0.2"})
    assert result["addr"] == "10.0.0.1 10.0.0.2"


def test_prefixed_vars_override_when_explicitly_set():
    result = _import_with(
        {
            "EPICS_CA_AUTO_ADDR_LIST": "YES",
            "DIRECT_CONTROL_EPICS_CA_AUTO_ADDR_LIST": "NO",
            "DIRECT_CONTROL_EPICS_CA_ADDR_LIST": "192.168.1.5",
        }
    )
    assert result["auto"] == "NO"
    assert result["addr"] == "192.168.1.5"


def test_nothing_set_leaves_libca_defaults_alone():
    """With no EPICS config at all, the module writes nothing into the env."""
    result = _import_with({})
    assert result["addr"] is None
    assert result["auto"] is None
