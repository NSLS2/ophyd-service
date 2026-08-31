"""Acceptance check: ophyd's EpicsMotor against the simulated IOS motor records.

Spawns ioc_ios_motor.py and the blackhole on ephemeral CA ports (the blackhole
excluding the motor records exactly as run_all_iocs.sh / reproduce.sh do), then
drives the sample bar with the profile's device class, classic ophyd
``EpicsMotor``:

    connect -> .VELO/.EGU come from the motor IOC (not fabricated)
    set(20) -> MoveStatus completes, the readback was seen ramping
    set(20) again (zero-distance) -> still completes (DMOV cycles)
    set(200) then stop() -> completes early, position < 200
    the blackhole alone does not answer Mtr.DMOV

This is the handshake ``mv(ioxas_x, pos)`` in a queued plan relies on. Run
from an environment with ophyd + pyepics + caproto (the profile's pixi qs env,
or any venv):

    python integration/queueserver-repro/iocs/verify_motor_sim.py
"""
import importlib.util
import os
import socket
import subprocess
import sys
import tempfile
import time

IOC_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, IOC_DIR)

from localguard import assert_local_epics  # noqa: E402

assert_local_epics()


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


P_MTR, P_BH = free_port(), free_port()
BAR = "XF:23ID2-BI{IOXAS:1-Ax:X}Mtr"

spec = importlib.util.spec_from_file_location("m_motor", f"{IOC_DIR}/ioc_ios_motor.py")
m_motor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m_motor)
motor_pvs = sorted(k for k in m_motor.build_pvdb() if not k.startswith("_"))
assert BAR in motor_pvs, motor_pvs

tmpdir = tempfile.mkdtemp(prefix="motor_verify_")
exclude = os.path.join(tmpdir, "exclude_pvs.txt")
with open(exclude, "w") as fh:
    fh.write("\n".join(motor_pvs) + "\n")
print(f"exclusions: {len(motor_pvs)} motor records")

procs = []


def spawn(script, port, extra_env=None):
    env = dict(os.environ, EPICS_CA_SERVER_PORT=str(port))
    env.update(extra_env or {})
    logf = open(os.path.join(tmpdir, script + ".log"), "w")
    p = subprocess.Popen([sys.executable, "-u", f"{IOC_DIR}/{script}", "--interfaces", "127.0.0.1"],
                         env=env, stdout=logf, stderr=subprocess.STDOUT)
    logf.close()  # the child holds its own FD
    procs.append(p)
    return p


def wait_listening(script, timeout=20):
    log = os.path.join(tmpdir, script + ".log")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(log) and "Listening on" in open(log).read():
            return
        time.sleep(0.2)
    raise RuntimeError(f"{script} did not start:\n" + open(log).read())


failures = []


def check(cond, msg):
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        failures.append(msg)


try:
    spawn("ioc_ios_motor.py", P_MTR)
    spawn("blackhole_ioc.py", P_BH, {"BLACKHOLE_EXCLUDE_PVS_FILE": exclude})
    wait_listening("ioc_ios_motor.py")
    wait_listening("blackhole_ioc.py")

    # 1) The blackhole alone must not answer a motor field.
    from caproto.sync.client import read as ca_read
    os.environ["EPICS_CA_ADDR_LIST"] = f"127.0.0.1:{P_BH}"
    try:
        ca_read(f"{BAR}.DMOV", timeout=1.5)
        check(False, "blackhole alone answered Mtr.DMOV (it must defer to the motor IOC)")
    except Exception:
        check(True, "blackhole alone does not answer Mtr.DMOV")

    # 2) ophyd EpicsMotor against both servers.
    os.environ["EPICS_CA_ADDR_LIST"] = f"127.0.0.1:{P_MTR} 127.0.0.1:{P_BH}"
    from ophyd import EpicsMotor

    bar = EpicsMotor(BAR, name="ioxas_x")
    bar.wait_for_connection(timeout=15)
    check(bar.velocity.get() == 10.0, f"VELO from the motor IOC = {bar.velocity.get()} (fabricated would be 0.0)")
    check(bar.motor_egu.get() == "mm", f"EGU = {bar.motor_egu.get()!r}")
    check(bar.low_limit_travel.get() == 0.0 and bar.high_limit_travel.get() == 300.0,
          f"limits = ({bar.low_limit_travel.get()}, {bar.high_limit_travel.get()})")

    samples = []
    bar.user_readback.subscribe(lambda value=None, **kw: samples.append(value), run=False)
    t0 = time.monotonic()
    st = bar.set(20.0)
    st.wait(timeout=15)
    dt = time.monotonic() - t0
    check(st.success, f"set(20.0) MoveStatus success={st.success} in {dt:.2f}s")
    check(abs(bar.position - 20.0) < 1e-6, f"position after move = {bar.position}")
    distinct = sorted(set(round(v, 3) for v in samples))
    check(len(distinct) >= 3, f"readback ramped through {len(distinct)} distinct values (expect >= 3 at 10 mm/s)")
    check(1.5 <= dt <= 4.0, f"20 mm at 10 mm/s took {dt:.2f}s (expect ~2s: real slew, not a jump)")

    t0 = time.monotonic()
    st2 = bar.set(20.0)
    st2.wait(timeout=5)
    check(st2.success and time.monotonic() - t0 < 2.0, "zero-distance set() completes (DMOV still cycles)")

    st3 = bar.set(200.0)
    time.sleep(0.6)
    bar.stop(success=True)
    st3.wait(timeout=5)
    check(st3.done and bar.position < 200.0, f"stop() mid-move: done={st3.done}, position={bar.position:.2f} (< 200)")
    time.sleep(0.5)  # the record re-asserts VAL = RBV on its next tick
    check(abs(bar.user_setpoint.get() - bar.position) < 0.05,
          f"after stop the setpoint follows the position ({bar.user_setpoint.get():.2f})")

    # 3) The other three axes connect too.
    for pv in motor_pvs:
        if pv == BAR:
            continue
        m = EpicsMotor(pv, name="m")
        m.wait_for_connection(timeout=10)
        check(m.velocity.get() > 0, f"{pv} connected, VELO={m.velocity.get()}")
finally:
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()

if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("motor acceptance: OK")
