"""
Regression tests for ``loader.py`` failure-handling.

Pre-2026-05-02, both ``HappiProfileLoader.load_registry`` and
``BitsProfileLoader.load_registry`` logged per-entry failures then
announced ``"Loaded N devices"`` — silently dropping bad entries and
seeding the registry from a partial load. The fix (M1) collects
failures and raises ``RuntimeError`` at the end of the loop, refusing
to seed from incomplete data. See feedback_no_silent_fallbacks.
"""

from __future__ import annotations

import json

import pytest
import yaml

from configuration_service.loader import BitsProfileLoader, HappiProfileLoader


# ─── M1 (Happi): aggregate per-entry failures must raise ────────────────────


def _write_happi_profile(profile_dir, entries: dict) -> None:
    """Write a happi_db.json into a profile directory and return the dir path.

    HappiProfileLoader takes a *directory* containing ``happi_db.json``,
    not the JSON file path itself.
    """
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "happi_db.json").write_text(json.dumps(entries))


def _good_happi_entry(name: str, prefix: str = "TST:") -> dict:
    """A minimum entry that ``_process_entry`` accepts cleanly."""
    return {
        "_id": name,
        "active": True,
        "args": ["{{prefix}}"],
        "kwargs": {"name": "{{name}}"},
        "type": "OphydItem",
        "device_class": "ophyd.EpicsMotor",
        "name": name,
        "prefix": prefix,
    }


def test_m1_happi_partial_failure_raises_with_aggregate_message(tmp_path, monkeypatch):
    """One bad entry among many must raise listing all failures."""
    profile = tmp_path / "profile"
    _write_happi_profile(
        profile,
        {
            "good_a": _good_happi_entry("good_a"),
            "bad_one": _good_happi_entry("bad_one"),
            "good_b": _good_happi_entry("good_b"),
            "bad_two": _good_happi_entry("bad_two"),
        },
    )

    loader = HappiProfileLoader(profile)
    real_process = loader._process_entry

    def fake_process(name, entry, registry):
        if name.startswith("bad"):
            raise ValueError(f"simulated failure for {name}")
        real_process(name, entry, registry)

    monkeypatch.setattr(loader, "_process_entry", fake_process)

    with pytest.raises(RuntimeError) as excinfo:
        loader.load_registry()

    # Both bad entries must appear; partial-load count must reflect reality.
    msg = str(excinfo.value)
    assert "Failed to load 2 of 4 happi entries" in msg, (
        f"aggregate count missing from error message: {msg!r}"
    )
    assert "bad_one: simulated failure for bad_one" in msg
    assert "bad_two: simulated failure for bad_two" in msg
    assert "refusing to seed registry from partial data" in msg


def test_m1_happi_all_good_loads_normally(tmp_path):
    """Sanity: with all-clean entries, load_registry returns the registry."""
    profile = tmp_path / "profile"
    _write_happi_profile(
        profile,
        {
            "alpha": _good_happi_entry("alpha"),
            "beta": _good_happi_entry("beta"),
        },
    )

    registry = HappiProfileLoader(profile).load_registry()

    assert "alpha" in registry.devices
    assert "beta" in registry.devices


def test_m1_happi_inactive_entries_are_not_failures(tmp_path, monkeypatch):
    """Pre-fix bug guard: inactive entries are skipped, not counted as failures."""
    profile = tmp_path / "profile"
    inactive = _good_happi_entry("dormant")
    inactive["active"] = False
    _write_happi_profile(
        profile,
        {
            "active_one": _good_happi_entry("active_one"),
            "dormant": inactive,
        },
    )

    loader = HappiProfileLoader(profile)
    real_process = loader._process_entry

    seen: list[str] = []

    def tracking_process(name, entry, registry):
        seen.append(name)
        real_process(name, entry, registry)

    monkeypatch.setattr(loader, "_process_entry", tracking_process)

    registry = loader.load_registry()
    assert seen == ["active_one"], (
        f"_process_entry should only be called for active entries; saw {seen!r}"
    )
    assert "active_one" in registry.devices
    assert "dormant" not in registry.devices


# ─── M1 (BITS): aggregate per-entry failures must raise ─────────────────────


def _write_bits_profile(profile_dir, devices: dict, iconfig: dict | None = None) -> None:
    """Write a minimal BITS-format profile dir at the given path."""
    configs = profile_dir / "configs"
    configs.mkdir(parents=True, exist_ok=True)
    (configs / "devices.yml").write_text(yaml.safe_dump(devices))
    if iconfig is not None:
        (configs / "iconfig.yml").write_text(yaml.safe_dump(iconfig))


def _good_bits_entry(name: str, prefix: str = "TST:") -> dict:
    return {
        "name": name,
        "prefix": prefix,
        "device_class": "EpicsMotor",
    }


def test_m1_bits_partial_failure_raises_with_aggregate_message(tmp_path, monkeypatch):
    """One bad BITS entry among many must raise listing all failures."""
    profile = tmp_path / "profile"
    _write_bits_profile(
        profile,
        {
            "ophyd": [
                _good_bits_entry("good_a"),
                _good_bits_entry("bad_one"),
                _good_bits_entry("good_b"),
            ],
        },
    )

    loader = BitsProfileLoader(profile)
    real_process = loader._process_entry

    def fake_process(name, entry, module_path, beamline, registry):
        if name.startswith("bad"):
            raise ValueError(f"simulated failure for {name}")
        real_process(name, entry, module_path, beamline, registry)

    monkeypatch.setattr(loader, "_process_entry", fake_process)

    with pytest.raises(RuntimeError) as excinfo:
        loader.load_registry()

    msg = str(excinfo.value)
    assert "Failed to load 1 of 3 BITS entries" in msg
    assert "bad_one: simulated failure for bad_one" in msg
    assert "refusing to seed registry from partial data" in msg


def test_m1_bits_missing_name_raises(tmp_path):
    """A device entry missing ``name`` must be reported as a failure (not silently skipped)."""
    profile = tmp_path / "profile"
    _write_bits_profile(
        profile,
        {
            "ophyd": [
                _good_bits_entry("named"),
                {"prefix": "TST:other", "device_class": "EpicsMotor"},  # missing name
            ],
        },
    )

    with pytest.raises(RuntimeError) as excinfo:
        BitsProfileLoader(profile).load_registry()

    msg = str(excinfo.value)
    assert "missing required 'name' field" in msg
    assert "Failed to load 1 of 2 BITS entries" in msg


def test_m1_bits_non_list_module_raises(tmp_path):
    """A module with a non-list device_entries must be reported as a failure."""
    profile = tmp_path / "profile"
    _write_bits_profile(
        profile,
        {
            "ophyd": [_good_bits_entry("ok")],
            "broken_module": "not a list",
        },
    )

    with pytest.raises(RuntimeError) as excinfo:
        BitsProfileLoader(profile).load_registry()

    msg = str(excinfo.value)
    assert "broken_module: not a list of device entries" in msg


def test_m1_bits_all_good_loads_normally(tmp_path):
    """Sanity: with all-clean entries, load_registry returns the registry."""
    profile = tmp_path / "profile"
    _write_bits_profile(
        profile,
        {
            "ophyd": [_good_bits_entry("alpha"), _good_bits_entry("beta")],
        },
    )

    registry = BitsProfileLoader(profile).load_registry()
    assert "alpha" in registry.devices
    assert "beta" in registry.devices
