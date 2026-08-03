"""Simulated Xspress3 fluorescence detector IOC for the IOS demo.

Serves the PVs at prefix ``XF:23ID2-ES{Xsp:1}:`` that the IOS profile's
``xs3`` device (nslsii ``build_xspress3_class``: 1 channel, MCArois 1-4,
HDF5 plugin at ``HDF1:``) touches when XAS_scan / E_ramp stages, triggers
and reads it. Everything else the 443-PV device tree declares still
resolves at the blackhole (this IOC's PVs are harvested into the
blackhole exclusion list by reproduce.sh via ``--list-pvs``).

Dynamics (event-driven, deterministic per trigger):
    * ``det1:Acquire`` <- 1 starts an acquisition: after ``AcquireTime``
      seconds the four ``MCA1ROI:{n}:Total_RBV`` values update and
      ``Acquire``/``Acquire_RBV`` drop back to 0. nslsii's
      ``Xspress3Trigger`` completes on exactly that 1 -> 0 edge.
    * ROI counts follow a soft-X-ray absorption model evaluated at the
      *live PGM energy*: this IOC subscribes (CA client) to
      ``XF:23ID2-OP{Mono}Enrgy-I`` on the PGM sim, reachable at the
      address in ``XS3_PGM_ADDR`` (set by reproduce.sh). During an
      ``E_ramp`` fly the repeated trigger_and_read cycles therefore trace
      out real-looking edge structure. Without ``XS3_PGM_ADDR`` the
      energy pins at a mid-edge default and a warning is logged once —
      counts still flow, they just don't vary.
    * mu(E) = background + per-edge arctan step + white-line Gaussian,
      for the L/K edges the IOS edge map actually scans (Mn_L, Ni_L,
      O_K, ...). ROI1 ("PFY") and ROI2 ("TFY") are proportional to
      mu(E); ROI3 ("ELASTIC") is flat-ish; ROI4 ("BKG") is background.
      Counts are Poisson samples scaled by AcquireTime.

The HDF5 file plugin records (``HDF1:*``) are served as properly typed
enum/char records so ophyd's FileStore staging writes
(``auto_save='Yes'``, ``file_write_mode='Stream'``, ``compression='zlib'``,
...) succeed; no file is actually written. Asyn port names are served as
``XSP3`` on both the cam and the plugin so ``validate_asyn_ports`` holds.

All PVs live in one flat PVGroup (the vortex-sim pattern): caproto
re-expands prefixes on SubGroup nesting, which collides with the literal
``{Xsp:1}`` braces in the NSLS-II naming convention.

Phase: IOS demo follow-up to the blackhole file-plugin fix — gives
XAS_scan real (simulated) PFY/TFY traces instead of flat zeros.
"""

import asyncio
import logging
import os
import threading
import time
from typing import List

import numpy as np

from caproto import ChannelType
from caproto.server import PVGroup, ioc_arg_parser, pvproperty, run

log = logging.getLogger(__name__)

PGM_ENERGY_PV = "XF:23ID2-OP{Mono}Enrgy-I"

# --------------------------------------------------------------------------
# Absorption model: edges the IOS edge map scans (energies in eV).
# mu(E) = BG + sum_e A_e * [step(E-E0) + white-line gaussian] with a weaker
# L2-like repeat ~11 eV above E0. Values chosen so any edge-window scan
# (start just below E0) shows a clear rise + white line, like a real
# TEY/PFY XAS trace.
# --------------------------------------------------------------------------
_EDGES = (
    # (name, E0 eV, amplitude)
    ("Ti_L", 456.0, 0.8),
    ("O_K", 543.0, 0.7),
    ("Mn_L", 640.0, 1.0),   # the repro's demo scan window (635-670)
    ("Fe_L", 707.0, 0.9),
    ("Ni_L", 852.7, 1.0),   # the Ni_L preset the vortex sim also models
    ("Cu_L", 931.0, 0.9),
)
_STEP_WIDTH = 1.5      # eV, arctan edge sharpness
_WHITELINE_FWHM = 2.5  # eV
_WHITELINE_GAIN = 1.8  # white line height relative to the step
_L2_SPLIT = 11.0       # eV, second (L2-like) feature above E0, half amplitude

_BASE_RATE = 2_000.0   # cts/s in ROI1 at mu = 1
_BG_MU = 0.15          # energy-independent background absorption

_DEFAULT_ENERGY = 645.0  # mid Mn_L window; used when no PGM is reachable

# ROI layout: (roi number, name served on MCA1ROI:{n}:Name, lo, hi)
_ROIS = (
    (1, "PFY", 300, 700),
    (2, "TFY", 100, 1900),
    (3, "ELASTIC", 900, 1100),
    (4, "BKG", 1500, 1900),
)


def _mu(energy_ev: float) -> float:
    """Synthetic absorption coefficient at ``energy_ev``."""
    sigma = _WHITELINE_FWHM / 2.3548
    mu = _BG_MU
    for _name, e0, amp in _EDGES:
        for center, scale in ((e0, 1.0), (e0 + _L2_SPLIT, 0.5)):
            x = (energy_ev - center) / _STEP_WIDTH
            step = 0.5 + np.arctan(x) / np.pi
            # Real post-edge absorption decays away from the edge; without
            # this, steps from every lower edge accumulate into a high flat
            # baseline that drowns the local edge contrast.
            if energy_ev > center:
                step *= np.exp(-(energy_ev - center) / 60.0)
            white = _WHITELINE_GAIN * np.exp(
                -0.5 * ((energy_ev - center) / sigma) ** 2
            )
            mu += amp * scale * (step + white)
    return float(mu)


class _PgmEnergyFollower:
    """CA-client subscription to the PGM sim's energy readback.

    Runs a caproto threading-client subscription against the address in
    ``XS3_PGM_ADDR``. ``energy`` returns the latest value, or the fixed
    default (with a one-time warning) when no PGM is configured.
    """

    def __init__(self):
        self._energy = _DEFAULT_ENERGY
        self._lock = threading.Lock()
        addr = os.environ.get("XS3_PGM_ADDR", "").strip()
        if addr:
            # The threading-client Context reads EPICS_CA_* from the
            # environment; set it before the thread races Context().
            # (The caproto SERVER side never reads EPICS_CA_ADDR_LIST,
            # so this cannot redirect our own served PVs.)
            os.environ["EPICS_CA_ADDR_LIST"] = addr
            os.environ["EPICS_CA_AUTO_ADDR_LIST"] = "NO"
            threading.Thread(
                target=self._subscribe, args=(addr,), daemon=True
            ).start()
        else:
            log.warning(
                "XS3_PGM_ADDR not set: ROI counts will not follow the PGM "
                "energy (pinned at %.1f eV)", _DEFAULT_ENERGY,
            )

    def _subscribe(self, addr):
        """Poll the PGM energy over one persistent CA circuit.

        A poll loop (5 Hz) is deliberately used instead of a CA monitor:
        caproto's threading-client Subscription does not activate when
        registered before the channel first connects (observed against
        caproto 1.x: CreateChanResponse arrives, EventAddRequest never
        sent), and the energy slews at <= 6.5 eV/s so 0.2 s polling
        resolves the ramp finely. The Context/PV live for the process.
        """
        try:
            from caproto.threading.client import Context

            self._ctx = Context()
            (self._pv,) = self._ctx.get_pvs(PGM_ENERGY_PV)
            self._pv.wait_for_connection(timeout=60)
            log.info("following PGM energy at %s (%s)", addr, PGM_ENERGY_PV)
            while True:
                response = self._pv.read()
                with self._lock:
                    self._energy = float(response.data[0])
                log.debug("PGM energy poll: %.3f", self._energy)
                time.sleep(0.2)
        except Exception:
            log.exception(
                "PGM energy follower stopped; ROI counts pinned at last "
                "value (started from %.1f eV). PV=%s addr=%s",
                _DEFAULT_ENERGY, PGM_ENERGY_PV, addr,
            )

    @property
    def energy(self) -> float:
        with self._lock:
            return self._energy


def _mirrored(attr: str, pv_name: str, **prop_kwargs) -> List[tuple]:
    """A setpoint pvproperty + its ``_RBV`` twin, write-mirrored.

    ophyd ``EpicsSignalWithRBV`` reads back on ``<pv>_RBV`` after writing
    ``<pv>``; the generated putter copies every accepted write onto the
    RBV so set-and-verify semantics hold.
    """
    rbv_attr = attr + "_rbv"
    setpoint = pvproperty(name=pv_name, **prop_kwargs)
    rbv = pvproperty(name=pv_name + "_RBV", read_only=True, **prop_kwargs)

    async def _mirror(group, instance, value, _rbv_attr=rbv_attr):
        await getattr(group, _rbv_attr).write(value)
        return value

    setpoint = setpoint.putter(_mirror)
    return [(attr, setpoint), (rbv_attr, rbv)]


def _no_yes(value=0):
    return dict(value=value, dtype=ChannelType.ENUM, enum_strings=["No", "Yes"])


def _make_cam_pvs() -> List[tuple]:
    """det1: (cam) records other than Acquire (which needs real dynamics)."""
    out: List[tuple] = []
    out += _mirrored("acquire_time", "det1:AcquireTime", value=0.1, precision=3)
    out += _mirrored("num_images", "det1:NumImages", value=1)
    out += _mirrored(
        "trigger_mode", "det1:TriggerMode", value=1, dtype=ChannelType.ENUM,
        enum_strings=["Software", "Internal", "IDC", "TTL Veto Only",
                      "TTL Both", "LVDS Veto Only", "LVDS Both"],
    )
    out += _mirrored("array_callbacks", "det1:ArrayCallbacks", **_no_yes(1))
    out.append(("erase", pvproperty(value=0, name="det1:ERASE")))
    out.append((
        "cam_port_name",
        pvproperty(value="XSP3", name="det1:PortName_RBV", read_only=True,
                   dtype=ChannelType.STRING),
    ))
    out.append((
        "cam_array_counter_rbv",
        pvproperty(value=0, name="det1:ArrayCounter_RBV", read_only=True),
    ))
    return out


def _make_roi_pvs() -> List[tuple]:
    """MCA1ROI:{n}: Total_RBV (data), Name (read at profile load), bounds."""
    out: List[tuple] = []
    for n, roi_name, lo, hi in _ROIS:
        out.append((
            f"roi{n}_total",
            pvproperty(value=0.0, name=f"MCA1ROI:{n}:Total_RBV",
                       read_only=True, precision=1),
        ))
        out.append((
            f"roi{n}_name",
            pvproperty(value=roi_name, name=f"MCA1ROI:{n}:Name",
                       dtype=ChannelType.STRING),
        ))
        out += _mirrored(f"roi{n}_min_x", f"MCA1ROI:{n}:MinX", value=lo)
        out += _mirrored(f"roi{n}_size_x", f"MCA1ROI:{n}:SizeX", value=hi - lo)
    return out


def _make_hdf_pvs() -> List[tuple]:
    """HDF1: file plugin records ophyd's FileStore staging touches."""
    out: List[tuple] = []
    out += _mirrored(
        "hdf_enable", "HDF1:EnableCallbacks", value=0,
        dtype=ChannelType.ENUM, enum_strings=["Disable", "Enable"],
    )
    for attr, pv in [
        ("hdf_blocking_callbacks", "HDF1:BlockingCallbacks"),
        ("hdf_auto_save", "HDF1:AutoSave"),
        ("hdf_auto_increment", "HDF1:AutoIncrement"),
        ("hdf_lazy_open", "HDF1:LazyOpen"),
        ("hdf_swmr_mode", "HDF1:SWMRMode"),
    ]:
        out += _mirrored(attr, pv, **_no_yes())
    out += _mirrored(
        "hdf_file_write_mode", "HDF1:FileWriteMode", value=0,
        dtype=ChannelType.ENUM, enum_strings=["Single", "Capture", "Stream"],
    )
    out += _mirrored(
        "hdf_compression", "HDF1:Compression", value=0,
        dtype=ChannelType.ENUM,
        enum_strings=["None", "N-bit", "szip", "zlib", "Blosc"],
    )
    out += _mirrored(
        "hdf_capture", "HDF1:Capture", value=0,
        dtype=ChannelType.ENUM, enum_strings=["Done", "Capturing"],
    )
    out += _mirrored("hdf_create_directory", "HDF1:CreateDirectory", value=0)
    out += _mirrored("hdf_num_capture", "HDF1:NumCapture", value=0)
    out += _mirrored("hdf_file_number", "HDF1:FileNumber", value=0)
    _char = dict(string_encoding="utf-8", max_length=256,
                 dtype=ChannelType.CHAR)
    out += _mirrored("hdf_file_path", "HDF1:FilePath", value="/tmp/xs3", **_char)
    out += _mirrored("hdf_file_name", "HDF1:FileName", value="xs3_sim", **_char)
    out += _mirrored(
        "hdf_file_template", "HDF1:FileTemplate", value="%s%s_%6.6d.h5",
        string_encoding="utf-8", max_length=64, dtype=ChannelType.CHAR,
    )
    out.append((
        "hdf_file_path_exists",
        pvproperty(value=1, name="HDF1:FilePathExists_RBV", read_only=True),
    ))
    out.append((
        "hdf_full_file_name",
        pvproperty(value="/tmp/xs3/xs3_sim_000000.h5",
                   name="HDF1:FullFileName_RBV", read_only=True, **_char),
    ))
    out.append((
        "hdf_num_captured",
        pvproperty(value=0, name="HDF1:NumCaptured_RBV", read_only=True),
    ))
    out.append((
        "hdf_plugin_type",
        pvproperty(value="NDFileHDF5", name="HDF1:PluginType_RBV",
                   read_only=True, dtype=ChannelType.STRING),
    ))
    out += _mirrored(
        "hdf_nd_array_port", "HDF1:NDArrayPort", value="XSP3",
        dtype=ChannelType.STRING,
    )
    out.append((
        "hdf_port_name",
        pvproperty(value="HDF1", name="HDF1:PortName_RBV", read_only=True,
                   dtype=ChannelType.STRING),
    ))
    out.append((
        "hdf_array_counter_rbv",
        pvproperty(value=0, name="HDF1:ArrayCounter_RBV", read_only=True),
    ))
    return out


class Xspress3SimIOC(PVGroup):
    """xs3 sim: cam trigger dynamics + 4 MCArois + HDF file plugin, flat."""

    acquire = pvproperty(value=0, name="det1:Acquire")
    acquire_rbv = pvproperty(value=0, name="det1:Acquire_RBV", read_only=True)
    # Diagnostic: the PGM energy this sim believes (updated per acquisition).
    sim_energy_rbv = pvproperty(
        value=_DEFAULT_ENERGY, name="Sim:Energy_RBV", read_only=True,
        precision=2,
    )

    # Assigned via locals so the class body can iterate (the vortex-sim
    # pattern) — pvproperty objects are class-level descriptors, so this
    # is equivalent to writing each assignment out longhand.
    for _attr, _pv in _make_cam_pvs() + _make_roi_pvs() + _make_hdf_pvs():
        locals()[_attr] = _pv
    del _attr, _pv

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pgm = _PgmEnergyFollower()
        self._trigger_count = 0

    @acquire.putter
    async def acquire(self, instance, value):
        """Acquisition cycle: 1 -> (AcquireTime) -> ROI update -> 0.

        nslsii's Xspress3Trigger completes its status object on the
        1 -> 0 edge of the readback, so the falling write is what
        unblocks trigger_and_read in the plan.
        """
        try:
            intval = int(value)
        except (TypeError, ValueError):
            intval = 1 if str(value).lower() in ("1", "acquire", "yes") else 0
        if intval != 1:
            await self.acquire_rbv.write(0)
            return 0

        await self.acquire_rbv.write(1)
        acquire_time = max(float(self.acquire_time.value), 0.001)
        await asyncio.sleep(acquire_time)

        # Deterministic-per-trigger Poisson counts at the live PGM energy.
        self._trigger_count += 1
        energy = self._pgm.energy
        await self.sim_energy_rbv.write(energy)
        mu = _mu(energy)
        rng = np.random.default_rng(
            (self._trigger_count * 1_000_003) ^ int(energy * 1000)
        )
        pfy = rng.poisson(_BASE_RATE * mu * acquire_time)
        tfy = rng.poisson(_BASE_RATE * 0.6 * mu * acquire_time)
        elastic = rng.poisson(_BASE_RATE * 0.25 * acquire_time * (1 + 0.02 * mu))
        bkg = rng.poisson(_BASE_RATE * 0.05 * acquire_time)

        await self.roi1_total.write(float(pfy))
        await self.roi2_total.write(float(tfy))
        await self.roi3_total.write(float(elastic))
        await self.roi4_total.write(float(bkg))
        counter = int(self.cam_array_counter_rbv.value) + 1
        await self.cam_array_counter_rbv.write(counter)
        await self.hdf_array_counter_rbv.write(counter)
        await self.hdf_num_captured.write(counter)

        # Falling edge: acquisition done.
        await self.acquire_rbv.write(0)
        return 0


def main():
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("XS3_DEBUG") else logging.INFO
    )
    # Prefix has matched literal braces (XF:23ID2-ES{Xsp:1}:); caproto
    # expands {macro} in PV names, so escape them. Per-PV names have no
    # braces.
    ioc_options, run_options = ioc_arg_parser(
        default_prefix="XF:23ID2-ES{{Xsp:1}}:",
        desc="Simulated IOS Xspress3 (xs3): trigger dynamics, XAS-shaped "
             "ROI counts following the PGM energy, typed HDF5 plugin PVs.",
    )
    ioc = Xspress3SimIOC(**ioc_options)
    run(ioc.pvdb, **run_options)


if __name__ == "__main__":
    main()
