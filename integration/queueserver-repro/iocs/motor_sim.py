"""Simulated EPICS motor records: caproto's ``FakeMotor`` with a faithful move.

Uses caproto's shipped ``caproto.ioc_examples.fake_motor_record.FakeMotor`` — a
FULL EPICS motor record (every field: VAL/RBV/VELO/ACCL/DMOV/MOVN/STOP/HLM/LLM/
EGU/…) driven by a simulator that ramps ``.RBV`` toward ``.VAL`` at ``.VELO``
and toggles ``.DMOV`` 1→0→1 around the move. That handshake is what ophyd's
``EpicsMotor.set()`` (``MoveStatus``), ophyd-async's ``Motor.set()`` and a
plain ``caput(VAL, wait=True)`` all wait on.

Ported from the HEX simulated beamline (hex-ob/hex-simulated-beamline,
iocs/sim_devices/motor_sim.py) — keep the two in step. Deltas from caproto's
stock simulator, all of which a real motor record does and the stock one
does not:

* **Blocking put-completion.** A real record holds CA put-completion until
  the move finishes. Sequence-token completion: each put gets a sequence
  number; the move loop marks the sequence it started with as done when THAT
  ramp finishes, so a retarget mid-move only completes after its own motion.
* **A guaranteed observable moving tick** (``num_steps >= 1``) so a
  zero/tiny-distance move still cycles ``.DMOV`` 1→0→1 — ophyd v1's
  ``MoveStatus`` hangs forever otherwise (``was_moving`` never becomes True).
* **STOP keeps position**: ``.STOP`` or ``.SPMG == Stop`` aborts the ramp and
  writes the current readback back into ``.VAL`` (as an internal write, so the
  put hook does not treat it as a new target).
* ``.DESC``, ``.EGU``, ``.VMAX`` and the dial limits ``.DHLM``/``.DLLM`` are
  populated (ophyd-async's fly ``prepare`` compares against VMAX and its move
  check against the dial limits; both read 0 on the stock record).

NSLS-II PV names contain literal ``{ }``; caproto runs ``str.format`` on a
PVGroup prefix, so :func:`motor_group` doubles the braces.

Dynamics are a constant-velocity slew at ``.VELO`` on ``tick_rate_hz`` ticks —
no acceleration ramp, no soft-limit enforcement (``.LVIO``), no limit switches,
no tweak logic, no homing, no dial/user offset.
"""

import caproto.ioc_examples.fake_motor_record as _fmr
from caproto.ioc_examples.fake_motor_record import (
    FakeMotor,
    broadcast_precision_to_fields,
)

TICK_RATE_HZ = 10.0


async def _motor_simulator(instance, async_lib, defaults=None, tick_rate_hz=TICK_RATE_HZ):
    """caproto's motor_record_simulator with put-completion and a guaranteed move phase."""
    if defaults is None:
        defaults = dict(
            velocity=0.1, precision=3, acceleration=1.0,
            resolution=1e-6, user_limits=(0.0, 100.0),
        )
    fields = instance.field_inst
    have_new_position = False
    # Put-completion state. A single busy flag let a put be released by the
    # PREVIOUS move's finish; the sequence token ties each put to its own ramp.
    move_state = {"target": None, "seq": 0, "done_seq": 0, "internal": False,
                  "stopped": 0}

    async def value_write_hook(fields, value):
        nonlocal have_new_position
        if move_state["internal"]:
            return  # the move loop writing .VAL itself (STOP path)
        move_state["target"] = value
        move_state["seq"] += 1
        my_seq = move_state["seq"]
        have_new_position = True
        while move_state["done_seq"] < my_seq:
            await async_lib.library.sleep(0.02)

    fields.value_write_hook = value_write_hook

    await instance.write_metadata(precision=defaults["precision"])
    await broadcast_precision_to_fields(instance)
    await fields.velocity.write(defaults["velocity"])
    await fields.seconds_to_velocity.write(defaults["acceleration"])
    await fields.motor_step_size.write(defaults["resolution"])
    low, high = defaults["user_limits"]
    await fields.user_low_limit.write(low)
    await fields.user_high_limit.write(high)
    # No dial/user offset in the sim, so the dial limits equal the user limits.
    await fields.dial_low_limit.write(low)
    await fields.dial_high_limit.write(high)
    await fields.max_velocity.write(defaults.get("max_velocity", defaults["velocity"]))
    await fields.engineering_units.write(defaults.get("egu", ""))
    await fields.description.write(
        defaults.get("description", "sim motor %s" % instance.pvname))

    while True:
        dwell = 1.0 / tick_rate_hz
        # The blocking hook stashes the target BEFORE caproto commits
        # instance.value, so prefer it while a put is being completed.
        seq_snapshot = move_state["seq"]
        target_pos = (move_state["target"] if move_state["target"] is not None
                      else instance.value)
        diff = target_pos - fields.user_readback_value.value
        total_time = abs(diff / fields.velocity.value)
        num_steps = int(total_time // dwell)
        if abs(diff) < 1e-9 and not have_new_position:
            if fields.stop.value != 0:
                await fields.stop.write(0)
            if move_state["stopped"]:
                # A real record leaves VAL = RBV after a stop. The put that was
                # stopped is only released (and its value committed to .VAL by
                # caproto) shortly AFTER the ramp ended, so watch for that
                # commit over the next few ticks and re-assert the stopped
                # position when it lands.
                move_state["stopped"] -= 1
                if abs(instance.value - fields.user_readback_value.value) > 1e-9:
                    move_state["internal"] = True
                    try:
                        await instance.write(fields.user_readback_value.value)
                    finally:
                        move_state["internal"] = False
                    move_state["stopped"] = 0
            await async_lib.library.sleep(dwell)
            continue
        if fields.stop.value != 0:
            await fields.stop.write(0)
        # At least one moving tick so a CA monitor sees DMOV 1->0->1.
        num_steps = max(num_steps, 1)

        await fields.done_moving_to_value.write(0)
        await fields.motor_is_moving.write(1)

        readback = fields.user_readback_value.value
        step_size = diff / num_steps
        resolution = max((fields.motor_step_size.value, 1e-10))
        for _ in range(num_steps):
            stopped = fields.stop.value != 0 or fields.stop_pause_move_go.value == "Stop"
            if stopped:
                if fields.stop.value != 0:
                    await fields.stop.write(0)
                move_state["internal"] = True
                try:
                    await instance.write(readback)
                finally:
                    move_state["internal"] = False
                move_state["target"] = readback  # a stopped move stays put
                move_state["stopped"] = 10  # ticks to watch for the late commit
                break
            readback += step_size
            await fields.user_readback_value.write(readback)
            await fields.dial_readback_value.write(readback)
            await fields.raw_readback_value.write(readback / resolution)
            await async_lib.library.sleep(dwell)
        else:
            await fields.user_readback_value.write(target_pos)

        await fields.motor_is_moving.write(0)
        await fields.done_moving_to_value.write(1)
        have_new_position = False
        # Release the puts this ramp covered; a retarget that arrived mid-move
        # bumped seq past the snapshot and stays pending. Never clear the
        # stashed target here: caproto commits instance.value only after the
        # blocked hook returns, and an iteration in that window would see the
        # stale old value and drive the motor back to it.
        if move_state["done_seq"] < seq_snapshot:
            move_state["done_seq"] = seq_snapshot


def patch_fake_motor():
    """Make every ``FakeMotor`` created afterwards use :func:`_motor_simulator`.

    ``FakeMotor``'s startup calls the module-level
    ``fake_motor_record.motor_record_simulator``; swapping it out is enough.
    """
    _fmr.motor_record_simulator = _motor_simulator


def motor_group(pv_name, *, velocity, limits, egu="mm", description=None,
                acceleration=0.2, resolution=1e-6, max_velocity=None):
    """A caproto ``FakeMotor`` PVGroup serving one motor record at ``pv_name``.

    ``pv_name`` is the record name as clients use it (``…Mtr``); braces are
    doubled here for caproto's ``str.format`` prefix step. Merge ``.pvdb``
    into an IOC and serve it — caproto resolves ``.VAL``/``.RBV``/… from the
    base channel, so ``--list-pvs`` shows only the record name.
    """
    escaped = pv_name.replace("{", "{{").replace("}", "}}")
    group = FakeMotor(
        prefix=escaped,
        velocity=velocity,
        acceleration=acceleration,
        user_limits=tuple(limits),
        resolution=resolution,
    )
    group.defaults["egu"] = egu
    group.defaults["max_velocity"] = max_velocity if max_velocity is not None else velocity
    group.defaults["description"] = description or ("sim motor %s" % pv_name)
    return group
