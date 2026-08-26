#!/usr/bin/env python3
"""Simulated IOS motor records — the sample bar and the axes the XAS edge plans move.

Serves real EPICS motor records (see motor_sim.py) for the EpicsMotor entries
the sample-manager flow and the profile's edge plans drive, so
``mv(ioxas_x, pos)`` completes with the DMOV handshake instead of hanging on a
blackhole-fabricated float:

    ioxas_x   XF:23ID2-BI{IOXAS:1-Ax:X}Mtr   sample bar; the real operator
                                             screen's presets are Out = 0,
                                             SAMPLE 1..6 = 252/259/267/276/282/290 mm
    diag3_y   XF:23ID2-BI{Diag:3-Ax:Y}Mtr    diagnostic 3 (edge_ascan positions it)
    au_mesh   XF:23ID2-BI{AuMesh:1-Ax:Y}Mtr  I0 gold mesh
    vortex_x  XF:23ID2-BI{Vortex:1-Ax:X}Mtr  Vortex In = -220 / Out = 0 (operator screen)

Limits and speeds are simulation values chosen to admit the operator-screen
presets; only the sample bar's and Vortex's ranges come from the real screens.
Every other EpicsMotor in the happi seed stays on the blackhole until it is
needed — add it here (one line) rather than teaching the blackhole about
motor fields.

Runs like the other ``ioc_ios_*.py`` scripts (``--list-pvs --interfaces …``,
``EPICS_CA_SERVER_PORT``); ``--list-pvs`` prints the record names, and the
blackhole treats a listed record as owning all of its ``.FIELD``s.
"""
from caproto.server import ioc_arg_parser, run

from motor_sim import motor_group, patch_fake_motor

IOS_MOTORS = {
    "XF:23ID2-BI{IOXAS:1-Ax:X}Mtr": dict(
        description="IOXAS sample bar X", velocity=10.0, limits=(0.0, 300.0)),
    "XF:23ID2-BI{Diag:3-Ax:Y}Mtr": dict(
        description="Diagnostic 3 Y", velocity=5.0, limits=(-100.0, 100.0)),
    "XF:23ID2-BI{AuMesh:1-Ax:Y}Mtr": dict(
        description="Au mesh (I0) Y", velocity=5.0, limits=(-100.0, 100.0)),
    "XF:23ID2-BI{Vortex:1-Ax:X}Mtr": dict(
        description="Vortex X (In=-220, Out=0)", velocity=10.0, limits=(-250.0, 10.0)),
}


def build_pvdb(motors=IOS_MOTORS):
    """The merged pvdb for ``motors`` (record name -> motor_group kwargs)."""
    patch_fake_motor()
    groups = [motor_group(pv, egu="mm", **cfg) for pv, cfg in motors.items()]
    pvdb = {}
    for group in groups:
        pvdb.update(group.pvdb)
    pvdb["_groups"] = groups  # keep the PVGroups alive; their startup drives the sim
    return pvdb


def main():
    _, run_options = ioc_arg_parser(
        default_prefix="", desc="Simulated IOS motor records (sample bar + edge-plan axes)")
    pvdb = build_pvdb()
    groups = pvdb.pop("_groups")
    run(pvdb, **run_options)
    del groups


if __name__ == "__main__":
    main()
