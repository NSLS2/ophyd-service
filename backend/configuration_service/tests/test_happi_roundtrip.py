"""happi seed round trip against a file the queueserver worker really emitted.

``tests/fixtures/happi_worker_emitted/happi_db.json`` is verbatim output of
``start-re-manager --existing-devices-happi`` (2026-08-27) over a profile that
built an ophyd-async ``KinetixDetector`` with a PathProvider and a classic
``ophyd.sim`` motor. It is the published happi contract as the other side of it
actually produces it — including the entry the worker had to demote
(``active: false``) because a constructor argument could not be serialized.

The contract this pins:

* an active entry loads with device_class / args / kwargs / framework intact;
* an inactive entry is skipped — but LOUDLY, with the reason the emitter wrote;
* exporting the registry as happi and loading the export again yields the same
  instantiation spec (the format round-trips through the service).
"""

from __future__ import annotations

import json
import logging
from argparse import Namespace
from pathlib import Path

from configuration_service.cli import _run_export
from configuration_service.loader import HappiProfileLoader

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "happi_worker_emitted"


def _spec_view(spec) -> dict:
    """The instantiation-relevant fields of a spec, for equality across a round trip."""
    return {
        "device_class": spec.device_class,
        "args": list(spec.args),
        "kwargs": dict(spec.kwargs),
        "framework": spec.framework,
    }


def test_active_entry_loads_with_full_instantiation_info():
    registry = HappiProfileLoader(FIXTURE_DIR).load_registry()

    assert "sim_motor" in registry.devices
    spec = registry.instantiation_specs["sim_motor"]
    assert spec.device_class == "ophyd.sim.SynAxis"
    assert list(spec.args) == []
    assert spec.kwargs == {"labels": ["motors"], "name": "motor"}
    assert spec.framework == "ophyd-sync"


def test_inactive_entry_is_skipped_loudly_with_the_emitters_reason(caplog):
    with caplog.at_level(logging.WARNING):
        registry = HappiProfileLoader(FIXTURE_DIR).load_registry()

    assert "kinetix1" not in registry.devices
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "kinetix1" in r.getMessage()]
    assert warnings, "an inactive device must be reported, not silently dropped"
    message = warnings[0].getMessage()
    # The reason the worker wrote into the entry travels into the log line.
    assert "non-serializable value replaced by repr" in message
    assert "ADWriterFactory" in message


def test_export_then_reload_preserves_the_instantiation_spec(tmp_path):
    exported = tmp_path / "export" / "happi_db.json"
    exported.parent.mkdir()
    rc = _run_export(
        Namespace(
            command="export",
            format="happi",
            output=str(exported),
            profile_path=str(FIXTURE_DIR),
            load_strategy="happi",
            use_mock_data=False,
        )
    )
    assert rc == 0

    payload = json.loads(exported.read_text())
    assert "sim_motor" in payload
    assert "kinetix1" not in payload  # never loaded, so never exported
    entry = payload["sim_motor"]
    assert entry["_id"] == entry["name"] == "sim_motor"
    assert entry["device_class"] == "ophyd.sim.SynAxis"
    assert entry["framework"] == "ophyd-sync"

    # The export is itself a loadable happi profile: round trip.
    original = HappiProfileLoader(FIXTURE_DIR).load_registry()
    reloaded = HappiProfileLoader(exported.parent).load_registry()
    assert _spec_view(reloaded.instantiation_specs["sim_motor"]) == _spec_view(
        original.instantiation_specs["sim_motor"]
    )


def test_fixture_is_the_worker_emission_shape():
    """Guard the fixture itself: it must keep the shape the worker writes."""
    db = json.loads((FIXTURE_DIR / "happi_db.json").read_text())
    kinetix = db["kinetix1"]
    assert kinetix["active"] is False
    assert kinetix["device_class"] == "ophyd_async.epics.adkinetix.KinetixDetector"
    assert kinetix["framework"] == "ophyd-async"
    assert kinetix["args"][0] == "XF:27ID1-ES{Kinetix:1}"
    assert kinetix["args"][1].startswith("ADWriterFactory(")  # the repr placeholder
    assert "non-serializable" in kinetix["documentation"]
