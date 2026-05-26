"""Simulated Vortex MCA IOC for the IOS demo.

Serves the PVs at prefix ``XF:23ID2-ES{Vortex}mca1.*`` that the IOS happi
entry references via ``ios_devs.Vortex`` (which wraps ``ophyd.EpicsMCA``).

Dynamics (event-driven, deterministic per PRTM value):
    * On startup AND on every write to ``.PRTM``: regenerate the spectrum
      as Poisson samples of a fixed mean-rate template scaled by PRTM.
      Template = flat background + two Gaussian peaks ("Ni La" near
      channel 300, "Ni Lb" near channel 600) so ROIs inside vs outside
      the peaks give distinguishably different sums.
    * On every write to ``.R{N}LO`` or ``.R{N}HI``: recompute the
      corresponding ROI scalar ``.R{N}`` from the current spectrum.
    * Eight ROIs (R0-R7). The IOS Ni_L preset writes R2 (vortex emission)
      and R4 (IPFY); both indices are covered.

The MCA's full feature set (32 ROIs, .ERAS/.STRT triggers, .ELTM live-time,
the DXP sub-record at ``dxp1:``) is intentionally subset — only what the
Ni_L exerciser flow needs.

Phase 3 of the IOS use case (dynamic IOCs).
"""

import asyncio
import logging
from typing import List

import numpy as np

from caproto.server import PVGroup, ioc_arg_parser, pvproperty, run


log = logging.getLogger(__name__)


# MCA channel count. Real Vortex uses 2048; mirrors that.
N_CHANNELS = 2048

# Number of ROIs to publish. Real MCA has 32; the IOS preset only writes
# R2 and R4, so 8 covers it with headroom.
N_ROIS = 8

# Spectrum mean-rate template (counts/sec/channel). Background + two peaks
# at channel 300 ("Ni La") and channel 600 ("Ni Lb") with FWHM 30. Pre-
# computed at import time — never changes.
_BACKGROUND = 5.0
_PEAK_POSITIONS = (300, 600)
_PEAK_HEIGHTS = (200.0, 100.0)  # cts/sec at peak center
_PEAK_FWHM = 30.0

_channels = np.arange(N_CHANNELS, dtype=np.float64)
_mean_rates = np.full(N_CHANNELS, _BACKGROUND, dtype=np.float64)
for _pos, _height in zip(_PEAK_POSITIONS, _PEAK_HEIGHTS):
    _sigma = _PEAK_FWHM / 2.3548
    _mean_rates += _height * np.exp(-0.5 * ((_channels - _pos) / _sigma) ** 2)


def _make_roi_pvs() -> List[tuple]:
    """Build the eight (name, pvproperty) pairs for R{N}LO/HI/sum.

    Returns a flat list of (attr_name, pvproperty_object). Caller assigns
    each as a class attribute. The R{N} sum is read_only (computed from
    the spectrum by the IOC).
    """
    out: List[tuple] = []
    for n in range(N_ROIS):
        # Default bounds spread across the spectrum — channel n*256 to
        # (n+1)*256-1, giving 8 contiguous octants by default.
        lo_default = n * (N_CHANNELS // N_ROIS)
        hi_default = (n + 1) * (N_CHANNELS // N_ROIS) - 1
        out.append((
            f"R{n}_lo",
            pvproperty(value=lo_default, name=f"mca1.R{n}LO"),
        ))
        out.append((
            f"R{n}_hi",
            pvproperty(value=hi_default, name=f"mca1.R{n}HI"),
        ))
        out.append((
            f"R{n}_sum",
            pvproperty(value=0, name=f"mca1.R{n}", read_only=True),
        ))
    return out


class VortexIOC(PVGroup):
    """Vortex MCA — 2048-channel spectrum + 8 ROIs.

    Cross-reference: ``integration/happi/sites/ios/ios_devs.py`` declares
    ``Vortex.mca = Cpt(EpicsMCA, "mca1")``, so PVs are at
    ``XF:23ID2-ES{Vortex}mca1.*``.
    """

    # ─── Spectrum + acquisition timing ───────────────────────────────────
    PRTM = pvproperty(value=1.0, name="mca1.PRTM", precision=4, units="s")
    ERTM = pvproperty(
        value=1.0,
        name="mca1.ERTM",
        read_only=True,
        precision=4,
        units="s",
    )
    # Spectrum is exposed as a waveform PV. caproto auto-sizes from the
    # initial value's length.
    spectrum = pvproperty(
        value=[0] * N_CHANNELS,
        name="mca1.VAL",
        read_only=True,
        max_length=N_CHANNELS,
    )

    # ─── ROIs (24 PVs: 8 × LO + 8 × HI + 8 × sum) ────────────────────────
    # Assigned via locals so the class body can iterate. pvproperty objects
    # are class-level descriptors; assigning at class-body time works the
    # same as writing them out explicitly.
    for _attr, _pv in _make_roi_pvs():
        locals()[_attr] = _pv
    del _attr, _pv

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Spectrum + ROI state. Spectrum is seeded once on startup and
        # re-rolled on every PRTM write. ROI sums recompute on every ROI-
        # bound write or PRTM write.
        self._spectrum_np = np.zeros(N_CHANNELS, dtype=np.int64)
        # Deterministic seed so tests don't see noise across runs.
        self._rng = np.random.default_rng(seed=42)

    @PRTM.startup
    async def _seed_spectrum(self, _instance, _async_lib):
        """One-shot at IOC startup: roll the spectrum + push all ROI sums."""
        await self._regenerate_spectrum()
        await self._refresh_all_rois()

    @PRTM.putter
    async def _on_prtm_write(self, _instance, value):
        # Regenerate spectrum with new PRTM scaling, then refresh every
        # ROI sum so readers see consistent values.
        if value <= 0:
            raise ValueError(f"PRTM must be > 0; got {value}")
        # The putter's `value` is the new value being set; caproto writes
        # it after the putter returns. Pre-compute spectrum assuming
        # value will be stored.
        self._spectrum_np = self._rng.poisson(_mean_rates * value).astype(np.int64)
        await self.spectrum.write(self._spectrum_np.tolist())
        await self.ERTM.write(float(value))
        # Refresh all ROI sums against the new spectrum.
        for n in range(N_ROIS):
            await self._refresh_roi(n)

    async def _regenerate_spectrum(self):
        prtm = self.PRTM.value
        self._spectrum_np = self._rng.poisson(_mean_rates * prtm).astype(np.int64)
        await self.spectrum.write(self._spectrum_np.tolist())
        await self.ERTM.write(float(prtm))

    async def _refresh_roi(self, n: int):
        lo_pv = getattr(self, f"R{n}_lo")
        hi_pv = getattr(self, f"R{n}_hi")
        sum_pv = getattr(self, f"R{n}_sum")
        lo = max(0, min(int(lo_pv.value), N_CHANNELS - 1))
        hi = max(0, min(int(hi_pv.value), N_CHANNELS - 1))
        if hi < lo:
            lo, hi = hi, lo
        roi_sum = int(self._spectrum_np[lo : hi + 1].sum())
        await sum_pv.write(roi_sum)

    async def _refresh_all_rois(self):
        for n in range(N_ROIS):
            await self._refresh_roi(n)


# Build dynamic ROI-bound putters that recompute the corresponding sum.
# We can't decorate inside the class body for dynamically-created
# pvproperties, so register the putters via the pvspec API after class
# creation. caproto allows .putter() to be invoked as a callable on the
# pvproperty descriptor.
def _make_roi_bound_putter(n: int):
    async def _putter(group: VortexIOC, _instance, value):
        # The putter's `value` is what's about to be stored. caproto writes
        # it after this returns, so we need to compute the sum from the
        # pending bounds (one of which is `value`). Easiest: store the new
        # value into the IOC's local state and recompute.
        # We can't write the bound here (would recurse). Instead, refresh
        # the ROI AFTER caproto stores the value, by scheduling a task.
        asyncio.create_task(_refresh_after_store(group, n))
    return _putter


async def _refresh_after_store(group: VortexIOC, n: int):
    # Brief delay so caproto's outer write has stored the new bound value.
    await asyncio.sleep(0.01)
    try:
        await group._refresh_roi(n)
    except Exception:
        log.exception("ROI refresh failed for R%d", n)


for _n in range(N_ROIS):
    _lo_attr = f"R{_n}_lo"
    _hi_attr = f"R{_n}_hi"
    getattr(VortexIOC, _lo_attr).putter(_make_roi_bound_putter(_n))
    getattr(VortexIOC, _hi_attr).putter(_make_roi_bound_putter(_n))
del _n, _lo_attr, _hi_attr


def main():
    # Prefix has matched braces (XF:23ID2-ES{Vortex}); escape both. After
    # expansion: XF:23ID2-ES{Vortex}. Per-PV names have no braces.
    ioc_options, run_options = ioc_arg_parser(
        default_prefix="XF:23ID2-ES{{Vortex}}",
        desc="IOS Vortex MCA simulation IOC (mca1.* with 8 ROIs).",
    )
    ioc = VortexIOC(**ioc_options)
    run(ioc.pvdb, **run_options)


if __name__ == "__main__":
    main()
