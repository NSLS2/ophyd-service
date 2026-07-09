#!/usr/bin/env python3
"""Catch-all ("black hole") EPICS IOC for the IOS demo pod.

The IOS profile collection instantiates ~100 ophyd devices spanning hundreds of
PVs (motors, scalers, an MCA, area-detector plugins, calc records, ...). For
phase 1 we only need every one of those PVs to *resolve* so the RE Manager can
open the profile with all devices connected. Rather than run a faithful IOC per
device, this IOC answers Channel Access searches for ANY PV name, fabricating a
channel whose type is inferred from the name (AreaDetector plugin fields, enums,
strings, and otherwise a float).

This is the standard bluesky "spoof beamline" technique. It binds to 0.0.0.0 so
other containers on the compose network can reach it (unlike the upstream
spoof_beamline.py, which is hard-wired to 127.0.0.1 for on-host CI use).

Phase 2 replaces this with the realistic per-device IOS IOCs under
integration/ioc/ioc_ios_*.py.
"""
import re
from collections import defaultdict

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


class BlackholeDB(defaultdict):
    """A pvdb that claims to contain every PV and fabricates channels lazily."""

    def __contains__(self, key):
        return True

    def __missing__(self, key):
        # Collapse common record/field suffixes onto their base PV so a record
        # and its fields share one fabricated channel.
        if key.endswith(('-SP', '-I', '-RB', '-Cmd')):
            base, _, _ = key.rpartition('-')
            return self[base]
        if key.endswith(('_RBV', ':RBV')):
            return self[key[:-4]]
        channel = self[key] = self.default_factory(key)
        return channel


def fabricate_channel(key):
    """Infer a reasonable channel type from a PV name."""
    if 'PluginType' in key:
        for pattern, val in PLUGIN_TYPE_PVS:
            if pattern.search(key):
                return ChannelString(value=val)
        return ChannelString(value='NDPluginStats')
    if 'ArrayPort' in key or 'PortName' in key:
        return ChannelString(value=key)
    if 'EnableCallbacks' in key or 'BlockingCallbacks' in key or 'WaitForPlugins' in key:
        return ChannelEnum(value=0, enum_strings=['Disabled', 'Enabled'])
    if 'ImageMode' in key:
        return ChannelEnum(value=0, enum_strings=['Single', 'Multiple', 'Continuous'])
    if 'TriggerMode' in key:
        return ChannelEnum(value=0, enum_strings=['Internal', 'External'])
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
    # Serve on all interfaces unless the caller overrode --interfaces.
    if not run_options.get('interfaces'):
        run_options['interfaces'] = ['0.0.0.0']
    run(BlackholeDB(fabricate_channel), **run_options)


if __name__ == '__main__':
    main()
