"""Test ophyd classes referenced by enrichment tests.

These classes live in a normal importable module (rather than inside a
test function) so the resolver and direct-control's enrichment endpoint
can find them via ``importlib.import_module``. They are *not* tests
themselves — naming starts with ``test_`` only to keep all
test-supporting files in the tests/ directory.

``WithFmtCpt`` exists specifically to trigger the
``needs_enrichment`` static outcome (FormattedComponent with a
``{self.parent.prefix}`` placeholder) which the enrichment fallback then
hands off to direct-control. The mock direct-control client in
``test_enrichment_fallback.py`` returns the pretend resolved PVs;
production direct-control would instantiate this class against a real
IOC and read each leaf's ``pvname``.
"""
from __future__ import annotations

from ophyd import Component as Cpt, Device, EpicsSignal, FormattedComponent as FmtCpt


class _Inner(Device):
    counter_via_fmt = FmtCpt(EpicsSignal, "{self.parent.prefix}counter")
    m1_via_fmt = FmtCpt(EpicsSignal, "{self.parent.prefix}m1")


class WithFmtCpt(Device):
    inner = Cpt(_Inner, "")
