"""Acceptance check: the real IOS xs3 device against the simulated beamline.

Spawns the xspress3 sim + PGM sim + blackhole on ephemeral CA ports,
instantiates the IOS profile's exact Xspress3 class (nslsii
build_xspress3_class, 443 PVs, split across the three servers), then:

    stage -> trigger/read below the Mn L3 edge -> slew the PGM onto the
    white line -> trigger/read again -> unstage

and asserts the PFY ROI shows the absorption-edge jump (> 2x). This is
the same chain XAS_scan/E_ramp exercises, minus the RunEngine.

Run from the profile's pixi qs environment (it has ophyd + nslsii):

    pixi run --manifest-path <profile>/pixi.toml -e qs \
        python integration/queueserver-repro/iocs/verify_xs3_sim.py
"""
import importlib.util
import os
import socket
import subprocess
import sys
import time

IOC_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, IOC_DIR)

# The sims reuse real IOS PV names: refuse to run against anything but
# loopback before any CA client (ophyd, caproto.sync) reads the environment.
from localguard import assert_local_epics  # noqa: E402

assert_local_epics()

def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0)); return s.getsockname()[1]

P_XS3, P_PGM, P_BH = free_port(), free_port(), free_port()

# Exclusion file: every PV the xs3 + pgm sims serve.
def pvdb_names(script, cls_name, **ctor):
    spec = importlib.util.spec_from_file_location("m_" + cls_name, f"{IOC_DIR}/{script}")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return sorted(getattr(m, cls_name)(**ctor).pvdb)

xs3_pvs = pvdb_names("ioc_ios_xspress3.py", "Xspress3SimIOC", prefix="XF:23ID2-ES{{Xsp:1}}:", macros={})
pgm_spec = importlib.util.spec_from_file_location("m_pgm", f"{IOC_DIR}/ioc_ios_pgm.py")
m_pgm = importlib.util.module_from_spec(pgm_spec); pgm_spec.loader.exec_module(m_pgm)
pgm_cls = [getattr(m_pgm, n) for n in dir(m_pgm) if n.endswith("IOC") and isinstance(getattr(m_pgm, n), type)][0]
pgm_pvs = sorted(pgm_cls(prefix="XF:23ID2-OP{{Mono", macros={}).pvdb)
import tempfile
_tmpdir = tempfile.mkdtemp(prefix="xs3_verify_")
exclude = os.path.join(_tmpdir, "exclude_pvs.txt")
with open(exclude, "w") as fh:
    fh.write("\n".join(xs3_pvs + pgm_pvs) + "\n")
print(f"exclusions: {len(xs3_pvs)} xs3 + {len(pgm_pvs)} pgm")

procs = []
def spawn(script, port, extra_env=None):
    env = dict(os.environ, EPICS_CA_SERVER_PORT=str(port))
    env.update(extra_env or {})
    logf = open(os.path.join(_tmpdir, script + ".log"), "w")
    p = subprocess.Popen([sys.executable, "-u", f"{IOC_DIR}/{script}", "--interfaces", "127.0.0.1"],
                         env=env, stdout=logf, stderr=subprocess.STDOUT)
    procs.append(p); return p

try:
    spawn("ioc_ios_pgm.py", P_PGM)
    spawn("ioc_ios_xspress3.py", P_XS3, {"XS3_PGM_ADDR": f"127.0.0.1:{P_PGM}"})
    spawn("blackhole_ioc.py", P_BH, {"BLACKHOLE_EXCLUDE_PVS_FILE": exclude})
    time.sleep(2.5)
    assert all(p.poll() is None for p in procs), "an IOC died at startup"

    os.environ["EPICS_CA_ADDR_LIST"] = f"127.0.0.1:{P_XS3} 127.0.0.1:{P_PGM} 127.0.0.1:{P_BH}"
    os.environ["EPICS_CA_AUTO_ADDR_LIST"] = "NO"

    from caproto.sync.client import read as ca_read, write as ca_write
    from ophyd import Component as Cpt
    from ophyd.areadetector import Xspress3Detector
    from nslsii.areadetector.xspress3 import Xspress3Trigger, build_xspress3_class, Xspress3HDF5Plugin

    def set_energy(ev, timeout=30):
        ca_write("XF:23ID2-OP{Mono}Enrgy-SP", ev, notify=True)
        t0 = time.time()
        while time.time() - t0 < timeout:
            cur = ca_read("XF:23ID2-OP{Mono}Enrgy-I").data[0]
            if abs(cur - ev) < 0.05:
                return cur
            time.sleep(0.2)
        raise TimeoutError(f"PGM never reached {ev}; at {cur}")

    cls = build_xspress3_class(
        channel_numbers=(1,), mcaroi_numbers=(1, 2, 3, 4), image_data_key="data",
        xspress3_parent_classes=(Xspress3Detector, Xspress3Trigger),
        extra_class_members={"hdf5plugin": Cpt(Xspress3HDF5Plugin, "HDF1:", name="h5p",
            root_path="/x", path_template="/x/%Y", resource_kwargs={})},
    )
    xs3 = cls(prefix="XF:23ID2-ES{Xsp:1}:", name="xs3")
    print("INSTANTIATED")
    roi1 = list(list(xs3.iterate_channels())[0].iterate_mcarois())[0]
    print("ROI1 name from IOC:", roi1.roi_name.get())

    xs3.stage()
    print("STAGED")

    def acquire_once():
        st = xs3.trigger()
        st.wait(timeout=10)
        sim_e = ca_read("XF:23ID2-ES{Xsp:1}:Sim:Energy_RBV").data[0]
        print(f"   (sim's view of energy: {sim_e:.2f} eV)")
        return roi1.total_rbv.get()

    e_lo = set_energy(635.0)   # below Mn L3
    pfy_lo = acquire_once()
    print(f"E={e_lo:.2f} eV  PFY={pfy_lo}")

    e_hi = set_energy(641.5)   # on the Mn L3 white line
    pfy_hi = acquire_once()
    print(f"E={e_hi:.2f} eV  PFY={pfy_hi}")

    xs3.unstage()
    print("UNSTAGED")

    ratio = pfy_hi / max(pfy_lo, 1)
    print(f"PFY edge jump ratio: {ratio:.2f}x")
    assert ratio > 2.0, "PFY did not respond to the absorption edge"
    print("ACCEPTANCE OK: stage + trigger + read + energy-coupled PFY")
finally:
    for p in procs:
        p.terminate()
    for p in procs:
        try: p.wait(timeout=5)
        except Exception: p.kill()
