"""Type-inference regression tests for the blackhole IOC.

Run with any environment that has caproto + pytest:

    pytest integration/queueserver-repro/iocs/test_blackhole_types.py

Guards the AreaDetector file-plugin vocabulary: ophyd's FileStore stage
signals write enum *strings* ('Yes', 'Single', ...) to these PVs, and a
fabricated float channel turns that into ``int(b'Yes', 0)`` -> ValueError
at stage time (the XAS_scan / Xspress3 HDF5-plugin failure; the SPECS
HDF5 plugin stages the same signals).
"""

import importlib.util
import pathlib

import pytest

caproto = pytest.importorskip("caproto")
from caproto import (  # noqa: E402
    ChannelChar,
    ChannelDouble,
    ChannelEnum,
    ChannelInteger,
    ChannelString,
)

_MODULE_PATH = pathlib.Path(__file__).with_name("blackhole_ioc.py")
_spec = importlib.util.spec_from_file_location("blackhole_ioc", _MODULE_PATH)
blackhole_ioc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(blackhole_ioc)

_XS3_HDF = "XF:23ID2-ES{Xsp:1}:HDF5:"


@pytest.fixture()
def db():
    return blackhole_ioc.BlackholeDB()


@pytest.mark.parametrize(
    "pv,channel_type,enum_strings",
    [
        # The stage-signal enums behind the XAS_scan failure.
        (_XS3_HDF + "AutoSave", ChannelEnum, ("No", "Yes")),
        (_XS3_HDF + "AutoIncrement", ChannelEnum, ("No", "Yes")),
        (_XS3_HDF + "LazyOpen", ChannelEnum, ("No", "Yes")),
        (_XS3_HDF + "SWMRMode", ChannelEnum, ("No", "Yes")),
        # ophyd writes 'Yes'/'No' to these, not 'Enabled'/'Disabled'.
        (_XS3_HDF + "BlockingCallbacks", ChannelEnum, ("No", "Yes")),
        (_XS3_HDF + "WaitForPlugins", ChannelEnum, ("No", "Yes")),
        # ... but EnableCallbacks is Disable/Enable (real AD NDPluginBase).
        (_XS3_HDF + "EnableCallbacks", ChannelEnum, ("Disable", "Enable")),
        (_XS3_HDF + "FileWriteMode", ChannelEnum, ("Single", "Capture", "Stream")),
        (_XS3_HDF + "Compression", ChannelEnum, ("None", "N-bit", "szip", "zlib", "Blosc")),
        # File name/path/template stay long char waveforms; numbers stay ints.
        (_XS3_HDF + "FileTemplate", ChannelChar, None),
        (_XS3_HDF + "FileNumber", ChannelInteger, None),
        # Plain numeric plugin fields keep fabricating as numbers.
        (_XS3_HDF + "Capture", ChannelDouble, None),
        (_XS3_HDF + "NumCapture", ChannelDouble, None),
        # Ordinary beamline PVs are untouched by the new rules.
        ("XF:23ID2-OP{Mono}Enrgy-SP", ChannelDouble, None),
    ],
)
def test_fabricated_channel_types(db, pv, channel_type, enum_strings):
    channel = db[pv]
    assert isinstance(channel, channel_type), type(channel).__name__
    if enum_strings is not None:
        assert tuple(channel.enum_strings) == enum_strings


def test_file_path_exists_is_truthy_integer(db):
    """ophyd refuses to stage a file plugin unless this readback is truthy."""
    channel = db[_XS3_HDF + "FilePathExists_RBV"]
    assert isinstance(channel, ChannelInteger)
    assert channel.value == 1


def test_plugin_type_reports_hdf5_writer(db):
    channel = db[_XS3_HDF + "PluginType_RBV"]
    assert isinstance(channel, ChannelString)
    assert channel.value == "NDFileHDF5"


def test_asyn_ports_are_one_consistent_name(db):
    """ophyd's validate_asyn_ports() requires each plugin's NDArrayPort to
    match a sibling's PortName; one constant fabricated port satisfies every
    device tree (fabricating the PV name made every port unique and failed
    validation on ophyd versions that enforce it)."""
    cam_port = db["XF:23ID2-ES{Xsp:1}:det1:PortName_RBV"]
    plugin_src = db[_XS3_HDF + "NDArrayPort_RBV"]
    assert isinstance(cam_port, ChannelString)
    assert cam_port.value == plugin_src.value == "BHPORT"


def test_rbv_suffix_collapses_onto_base_channel(db):
    """A record and its _RBV share one fabricated channel (readback echo)."""
    assert db[_XS3_HDF + "AutoSave_RBV"] is db[_XS3_HDF + "AutoSave"]


def _db_with_exclusions(monkeypatch, tmp_path, names):
    exclude = tmp_path / "exclude_pvs.txt"
    exclude.write_text("\n".join(names) + "\n")
    monkeypatch.setenv("BLACKHOLE_EXCLUDE_PVS_FILE", str(exclude))
    spec = importlib.util.spec_from_file_location("blackhole_ioc_excl", _MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.BlackholeDB()


def test_excluded_record_owns_its_fields(monkeypatch, tmp_path):
    """A motor IOC lists only '...Mtr' under --list-pvs but answers every
    field; the blackhole must stay silent on Mtr.DMOV/.RBV/... too."""
    mtr = "XF:23ID2-BI{IOXAS:1-Ax:X}Mtr"
    db2 = _db_with_exclusions(monkeypatch, tmp_path, [mtr])
    assert mtr not in db2
    for field in ("DMOV", "RBV", "VELO", "EGU", "STOP"):
        assert f"{mtr}.{field}" not in db2
        with pytest.raises(KeyError):
            db2[f"{mtr}.{field}"]
    # An unrelated motor is still fabricated, fields included.
    other = "XF:23ID2-BI{Diag:1-Ax:Y}Mtr"
    assert other in db2 and f"{other}.DMOV" in db2
    assert isinstance(db2[f"{other}.DMOV"], ChannelDouble)


def test_field_rule_needs_the_record_itself_listed(monkeypatch, tmp_path):
    """The scaler lists its fields (.S1, .CNT, ...) individually, never the bare
    record, so an unserved field like .DLY must still fall through here."""
    sclr = "XF:23ID2-ES{Sclr:1}"
    db2 = _db_with_exclusions(monkeypatch, tmp_path, [f"{sclr}.S1", f"{sclr}.CNT"])
    assert f"{sclr}.S1" not in db2
    assert f"{sclr}.DLY" in db2
    assert isinstance(db2[f"{sclr}.DLY"], ChannelDouble)


def test_asyn_port_name_is_env_overridable(monkeypatch):
    """BLACKHOLE_ASYN_PORT renames the fabricated asyn port, so two
    fabricated device trees can coexist without claiming the same name."""
    monkeypatch.setenv("BLACKHOLE_ASYN_PORT", "BH2")
    spec = importlib.util.spec_from_file_location("blackhole_ioc_bh2", _MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    db2 = mod.BlackholeDB()
    assert db2["XF:23ID2-ES{Xsp:1}:det1:PortName_RBV"].value == "BH2"


# ---------------------------------------------------------------------------
# Live Channel Access round-trip: the exact operation XAS_scan staging does.
# ---------------------------------------------------------------------------


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_blackhole():
    """Run blackhole_ioc.py as a real CA server on an ephemeral port.

    Yields (env, port) where env carries the EPICS_CA_* settings a client
    needs. Skipped if the port comes up unusable in this sandbox.
    """
    import os
    import subprocess
    import sys
    import time

    port = _free_port()
    env = dict(
        os.environ,
        EPICS_CA_SERVER_PORT=str(port),
        EPICS_CA_ADDR_LIST=f"127.0.0.1:{port}",
        EPICS_CA_AUTO_ADDR_LIST="NO",
    )
    proc = subprocess.Popen(
        [sys.executable, str(_MODULE_PATH), "--interfaces", "127.0.0.1"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1.5)  # caproto binds fast; generous for slow CI
    try:
        if proc.poll() is not None:
            pytest.skip("blackhole IOC failed to start on an ephemeral port")
        yield env
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_ca_write_yes_to_autosave_roundtrips(live_blackhole, monkeypatch):
    """caput('Yes') to a fabricated AutoSave PV — the operation that raised
    ``invalid literal for int() with base 0: b'Yes'`` before the fix."""
    for key, value in live_blackhole.items():
        if key.startswith("EPICS_CA"):
            monkeypatch.setenv(key, value)
    from caproto import ChannelType
    from caproto.sync.client import read, write

    pv = _XS3_HDF + "AutoSave"
    write(pv, "Yes", notify=True)
    response = read(pv, data_type=ChannelType.STRING)
    assert response.data[0] == b"Yes"


def test_ca_write_stage_sig_set_roundtrips(live_blackhole, monkeypatch):
    """The other enum stage signals accept their ophyd-written strings."""
    for key, value in live_blackhole.items():
        if key.startswith("EPICS_CA"):
            monkeypatch.setenv(key, value)
    from caproto import ChannelType
    from caproto.sync.client import read, write

    for pv, value in [
        (_XS3_HDF + "AutoIncrement", "Yes"),
        (_XS3_HDF + "FileWriteMode", "Single"),
        (_XS3_HDF + "BlockingCallbacks", "Yes"),
    ]:
        write(pv, value, notify=True)
        response = read(pv, data_type=ChannelType.STRING)
        assert response.data[0] == value.encode(), pv
