#!/usr/bin/env python3
"""Catch-all ("black hole") EPICS IOC for the IOS queueserver demo.

The IOS profile collection instantiates ~100 ophyd devices spanning hundreds of
PVs. To open the profile under the RE Manager, every PV a device force-connects
at startup must *resolve*. Rather than run a faithful IOC per device, this IOC
answers Channel Access searches for ANY PV name, fabricating a channel whose
type is inferred from the name (AreaDetector plugin fields, enums, strings, and
otherwise a float). This is the standard bluesky "spoof beamline" technique.

Ported from the demo/ios-nsls2-queueserver phase-1 pod. Added here: an
exclusion set (BLACKHOLE_EXCLUDE_PVS_FILE, one PV name per line) of the exact
PVs served by the realistic per-device IOS IOCs (ioc_ios_*.py). This IOC will
not answer those PVs — nor the ``.FIELD``s of a listed record, since a record
IOC lists only the record name — so the realistic IOCs serve them without a
Channel Access duplicate-PV race — while every OTHER PV (including sub-PVs of the same
devices that the realistic IOCs happen not to serve) still resolves here, so
the whole profile opens quickly.
"""
import os
import re

from caproto import (ChannelChar, ChannelData, ChannelDouble, ChannelEnum,
                     ChannelInteger, ChannelString)
from caproto.server import ioc_arg_parser, run

# AreaDetector plugin type PVs must report a plausible plugin class so ophyd's
# AD device trees instantiate.
PLUGIN_TYPE_PVS = [
    (re.compile(r'image\d:'), 'NDPluginStdArrays'),
    (re.compile(r'Stats\d:'), 'NDPluginStats'),
    (re.compile(r'CC\d:'), 'NDPluginColorConvert'),
    (re.compile(r'Proc\d:'), 'NDPluginProcess'),
    (re.compile(r'Over\d:'), 'NDPluginOverlay'),
    (re.compile(r'ROI\d:'), 'NDPluginROI'),
    (re.compile(r'Trans\d:'), 'NDPluginTransform'),
    (re.compile(r'HDF\d:'), 'NDFileHDF5'),
    (re.compile(r'TIFF\d:'), 'NDFileTIFF'),
    (re.compile(r'SumAll'), 'NDPluginStats'),
]


def _load_excluded_pvs():
    """Exact PV names the realistic IOCs own; this IOC defers to them."""
    path = os.environ.get("BLACKHOLE_EXCLUDE_PVS_FILE", "")
    if not path or not os.path.exists(path):
        return frozenset()
    with open(path, "r", encoding="utf-8") as fh:
        return frozenset(line.strip() for line in fh if line.strip())


EXCLUDE_PVS = _load_excluded_pvs()

# One constant asyn port name keeps every fabricated AreaDetector plugin graph
# self-consistent (see fabricate_channel). Overridable so two fabricated
# device trees can coexist without claiming the same port name.
ASYN_PORT = os.environ.get("BLACKHOLE_ASYN_PORT", "BHPORT")


def is_excluded(key):
    """True when a realistic IOC owns ``key``: listed exactly, or a ``.FIELD``
    of a listed record. A record IOC (caproto ``record='motor'`` etc.) lists
    only the record name under ``--list-pvs`` and answers every field of it,
    so answering ``…Mtr.DMOV`` here would race the motor IOC."""
    if key in EXCLUDE_PVS:
        return True
    base, dot, _ = key.partition('.')
    return bool(dot) and base in EXCLUDE_PVS


class BlackholeDB(dict):
    """A pvdb that claims every PV except the ones a realistic IOC owns."""

    def __contains__(self, key):
        return not is_excluded(key)

    def __missing__(self, key):
        if is_excluded(key):
            # Owned by a realistic IOC — let Channel Access find it there.
            raise KeyError(key)
        # Collapse common record/field suffixes onto their base PV so a record
        # and its fields share one fabricated channel.
        if key.endswith(('-SP', '-I', '-RB', '-Cmd')):
            base, _, _ = key.rpartition('-')
            return self[base]
        if key.endswith(('_RBV', ':RBV')):
            return self[key[:-4]]
        channel = self[key] = fabricate_channel(key)
        return channel


def fabricate_channel(key):
    """Infer a reasonable channel type from a PV name.

    The AreaDetector file-plugin rules mirror the HEX simulated beamline's
    spoof IOC: ophyd's FileStore stage_sigs write enum *strings* ('Yes',
    'Single', ...) to these PVs, and a fabricated float channel turns that
    into ``int(b'Yes', 0)`` -> ValueError at stage time (the XAS_scan /
    Xspress3 HDF5-plugin failure; the SPECS HDF5 plugin stages the same way).
    """
    if 'PluginType' in key:
        for pattern, val in PLUGIN_TYPE_PVS:
            if pattern.search(key):
                return ChannelString(value=val)
        return ChannelString(value='NDPluginStats')
    if 'ArrayPort' in key or 'PortName' in key:
        # One constant asyn port name keeps every fabricated AreaDetector
        # plugin graph self-consistent: ophyd's validate_asyn_ports()
        # requires each plugin's NDArrayPort to name a port some sibling
        # (the cam) reports as its PortName. Fabricating the PV name here
        # (the old behavior) made every port unique and failed validation
        # on ophyd versions that enforce it.
        return ChannelString(value=ASYN_PORT)
    if 'EnableCallbacks' in key:
        # Real AD NDPluginBase uses 'Disable'/'Enable' (ophyd stages the
        # int 1, so either works live — match the real records anyway).
        return ChannelEnum(value=0, enum_strings=['Disable', 'Enable'])
    if 'BlockingCallbacks' in key or 'WaitForPlugins' in key:
        # ophyd writes 'Yes'/'No' strings to these, not 'Enabled'/'Disabled'.
        return ChannelEnum(value=0, enum_strings=['No', 'Yes'])
    if 'Auto' in key or 'LazyOpen' in key or 'SWMRMode' in key:
        # AutoSave / AutoIncrement / LazyOpen / SWMRMode — file-plugin bo
        # records staged as 'Yes'/'No'.
        return ChannelEnum(value=0, enum_strings=['No', 'Yes'])
    if 'ImageMode' in key:
        return ChannelEnum(value=0, enum_strings=['Single', 'Multiple', 'Continuous'])
    if 'TriggerMode' in key:
        return ChannelEnum(value=0, enum_strings=['Internal', 'External'])
    if 'FileWriteMode' in key or 'WriteMode' in key:
        return ChannelEnum(value=0, enum_strings=['Single', 'Capture', 'Stream'])
    if 'Compression' in key:
        # Real NDFileHDF5 capitalizes 'Blosc'.
        return ChannelEnum(value=0, enum_strings=['None', 'N-bit', 'szip', 'zlib', 'Blosc'])
    if 'FilePathExists' in key:
        # ophyd verifies this readback is truthy before staging a file plugin.
        return ChannelInteger(value=1)
    if 'ArraySize' in key:
        return ChannelData(value=10)
    if key.endswith('.EGU'):
        return ChannelString(value='mm')
    if 'filenumber' in key.lower():
        return ChannelInteger(value=0)
    if 'file' in key.lower() and 'mode' not in key.lower():
        return ChannelChar(value='a' * 250)
    return ChannelDouble(value=0.0)


def main():
    _, run_options = ioc_arg_parser(default_prefix='', desc='IOS demo PV black hole')
    if not run_options.get('interfaces'):
        run_options['interfaces'] = ['127.0.0.1']
    run(BlackholeDB(), **run_options)


if __name__ == '__main__':
    main()
