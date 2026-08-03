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
