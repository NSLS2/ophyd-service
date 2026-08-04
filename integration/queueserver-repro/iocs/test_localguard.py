"""Beamline-guard tests: sim EPICS clients refuse non-loopback networks.

Proves the safeguard behind the repro's local-only requirement: a client
process whose EPICS address list points at anything that could be a
beamline subnet must refuse to start, and a loopback-only environment must
pass. Exercises ``localguard.assert_local_epics`` in subprocesses (it
exits the process on violation), including through the real entry points
(``verify_xs3_sim.py``, the xs3 sim's PGM follower).

Run with any environment that has pytest:

    pytest integration/queueserver-repro/iocs/test_localguard.py
"""

import os
import pathlib
import socket
import subprocess
import sys

IOC_DIR = pathlib.Path(__file__).resolve().parent

SNIPPET = (
    "import sys; sys.path.insert(0, %r); "
    "from localguard import assert_local_epics; assert_local_epics(); "
    "print('STARTED')" % str(IOC_DIR)
)


def _run(env_extra, argv, timeout=60):
    env = dict(os.environ)
    env.pop("EPICS_CA_ADDR_LIST", None)
    env.pop("EPICS_PVA_ADDR_LIST", None)
    env.update(env_extra)
    return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout)


def _refused(result):
    return result.returncode != 0 and "localguard: REFUSING" in (
        result.stderr + result.stdout
    )


def test_beamline_addr_refused():
    r = _run({"EPICS_CA_ADDR_LIST": "10.68.27.11"}, [sys.executable, "-c", SNIPPET])
    assert _refused(r), (r.returncode, r.stdout, r.stderr)


def test_mixed_addrs_refused():
    """One bad entry among loopback ones still refuses."""
    r = _run(
        {"EPICS_CA_ADDR_LIST": "127.0.0.1 xf23id2-ioc1"},
        [sys.executable, "-c", SNIPPET],
    )
    assert _refused(r), (r.returncode, r.stdout, r.stderr)


def test_pva_addr_refused():
    r = _run(
        {"EPICS_CA_ADDR_LIST": "127.0.0.1", "EPICS_PVA_ADDR_LIST": "10.68.27.11"},
        [sys.executable, "-c", SNIPPET],
    )
    assert _refused(r), (r.returncode, r.stdout, r.stderr)


def test_loopback_passes():
    r = _run(
        {"EPICS_CA_ADDR_LIST": "127.0.0.1 127.0.0.1:5064"},
        [sys.executable, "-c", SNIPPET],
    )
    assert not _refused(r) and "STARTED" in r.stdout, (r.returncode, r.stderr)


def test_cli_refuses_non_loopback_argument():
    """reproduce.sh hands the computed RE-worker address list to this CLI."""
    r = _run({}, [sys.executable, str(IOC_DIR / "localguard.py"), "10.68.27.11:5064"])
    assert _refused(r), (r.returncode, r.stdout, r.stderr)


def test_cli_passes_loopback_arguments():
    r = _run(
        {},
        [
            sys.executable,
            str(IOC_DIR / "localguard.py"),
            "127.0.0.1:5064",
            "127.0.0.1:5066",
        ],
    )
    assert r.returncode == 0 and "localguard: OK" in r.stdout, (r.stdout, r.stderr)


def test_verify_entry_point_refuses_beamline_addr():
    """The acceptance script refuses before spawning IOCs or touching CA."""
    r = _run(
        {"EPICS_CA_ADDR_LIST": "10.68.27.11"},
        [sys.executable, str(IOC_DIR / "verify_xs3_sim.py")],
    )
    assert _refused(r), (r.returncode, r.stdout, r.stderr)


def test_xs3_sim_refuses_non_loopback_pgm_addr():
    """The xs3 sim's PGM energy follower is a CA client: a non-loopback
    XS3_PGM_ADDR must abort the IOC before any subscription starts."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    r = _run(
        {
            "XS3_PGM_ADDR": "10.68.27.11:5064",
            "EPICS_CA_SERVER_PORT": str(port),
        },
        [
            sys.executable,
            str(IOC_DIR / "ioc_ios_xspress3.py"),
            "--interfaces",
            "127.0.0.1",
        ],
    )
    assert _refused(r), (r.returncode, r.stdout, r.stderr)
