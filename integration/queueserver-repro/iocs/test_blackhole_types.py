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
        # ... but EnableCallbacks really is Disabled/Enabled.
        (_XS3_HDF + "EnableCallbacks", ChannelEnum, ("Disabled", "Enabled")),
        (_XS3_HDF + "FileWriteMode", ChannelEnum, ("Single", "Capture", "Stream")),
        (_XS3_HDF + "Compression", ChannelEnum, ("None", "N-bit", "szip", "zlib", "blosc")),
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


def test_rbv_suffix_collapses_onto_base_channel(db):
    """A record and its _RBV share one fabricated channel (readback echo)."""
    assert db[_XS3_HDF + "AutoSave_RBV"] is db[_XS3_HDF + "AutoSave"]


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
