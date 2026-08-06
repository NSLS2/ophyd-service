"""Beamline guard: refuse to run sim-side EPICS clients unless loopback-only.

The IOS sim IOCs and the blackhole deliberately reuse REAL IOS PV names so
the profile collection runs unmodified. That means any sim-side CA client
(the RE worker, the xs3 sim's PGM energy follower, the acceptance and test
scripts — things that WRITE to real-named PVs) pointed at the wrong network
would address the real beamline. Deployment work targets IOS hosts
(xf23id2-ios-qs1), where a stray or inherited address list routes to real
IOCs. Enforce, don't trust configuration.

``assert_local_epics()`` therefore:

* forces ``EPICS_CA_AUTO_ADDR_LIST=NO`` / ``EPICS_PVA_AUTO_ADDR_LIST=NO``
  (no broadcast searching, ever), and
* requires every entry of ``EPICS_CA_ADDR_LIST`` / ``EPICS_PVA_ADDR_LIST``
  to be a loopback address (127.0.0.0/8 or ``localhost``), aborting loudly
  otherwise.

Call it BEFORE importing ``epics``/``p4p`` or creating a caproto client
Context — those read the environment at import/Context time. Servers are
out of scope: the caproto IOCs bind ``--interfaces 127.0.0.1`` explicitly,
and the caproto server side never reads ``EPICS_CA_ADDR_LIST``.

Runnable as a script for shell callers (reproduce.sh): validates the
environment plus any addresses passed as arguments, exit 2 on violation.

    python localguard.py 127.0.0.1:5064 127.0.0.1:5066

Ported from the HEX simulated beamline (iocs/panda/localguard.py).
"""

import ipaddress
import os
import sys


def _is_loopback(entry):
    host = entry.rsplit(":", 1)[0] if ":" in entry else entry
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False  # unresolvable / hostname: reject, loopback must be explicit


def assert_loopback_addrs(addrs, context):
    """Exit(2) unless every address in ``addrs`` is loopback."""
    bad = [e for e in addrs if not _is_loopback(e)]
    if bad:
        print(
            "localguard: REFUSING to start — non-loopback EPICS address(es) "
            "%s (from %s). The IOS sim uses REAL beamline PV names; running "
            "its clients against a beamline network could drive real "
            "devices. Use 127.0.0.1 entries only." % (bad, context),
            file=sys.stderr,
        )
        sys.exit(2)


def assert_local_epics(default_ca="127.0.0.1", default_pva="127.0.0.1"):
    """Force + validate a loopback-only EPICS client environment or exit(2)."""
    os.environ["EPICS_CA_AUTO_ADDR_LIST"] = "NO"
    os.environ["EPICS_PVA_AUTO_ADDR_LIST"] = "NO"
    ca = os.environ.get("EPICS_CA_ADDR_LIST") or default_ca
    pva = os.environ.get("EPICS_PVA_ADDR_LIST") or default_pva
    os.environ["EPICS_CA_ADDR_LIST"] = ca
    os.environ["EPICS_PVA_ADDR_LIST"] = pva
    assert_loopback_addrs(
        ca.split() + pva.split(), "EPICS_CA_ADDR_LIST/EPICS_PVA_ADDR_LIST"
    )
    return ca


def main(argv):
    ca = assert_local_epics()
    if argv:
        assert_loopback_addrs(argv, "command line")
    print("localguard: OK (loopback-only): %s" % " ".join(argv or ca.split()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
