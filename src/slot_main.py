"""Stable root launcher installed as /main.py by A/B project assembly.

Boot flow (A/B safety, see ``lib/coresys/post.py``):

1. Select a slot and (for a candidate) arm the watchdog supervision.
2. Import the guest application -- this creates its singletons but does NOT
   start its control loop (``main()`` is called later).
3. Run the framework POST (framework checks + the guest's optional
   ``post_checks()`` hook) and record the boot context.
4. Decide:
   * candidate + POST fail -> ``rollback_candidate`` + clean reboot (never
     promoted, version quarantined);
   * candidate + POST pass -> ``confirm_running_slot`` (inside the 12 s
     window), then run ``main()`` briefly so a bad ``main()`` is still caught
     and rolled back before the watchdog's one clean reset;
   * active slot -> run ``main()`` (degraded context if the POST failed, so
     the guest holds actuation and the board never reboots on its own).
"""

import uasyncio as asyncio
import machine

from lib.coresys.slot_manager import (
    activate_slot_path,
    confirm_running_slot,
    prepare_slot_boot,
    rollback_candidate,
)
from lib.coresys.watchdog import watchdog_owner
from lib.coresys import post


def output_reset_cause():
    try:
        cause = machine.reset_cause()
    except (AttributeError, OSError):
        cause = "unavailable"
    print("A/B launcher reset cause: %s" % cause)
    return cause


async def launch():
    output_reset_cause()
    slot, is_candidate, state = prepare_slot_boot()
    activate_slot_path(slot)
    if is_candidate:
        print("Supervising candidate slot %s with watchdog" % slot)
        watchdog_owner.start_supervision(slot)

    # Import the guest application (creates its singletons; the control loop
    # only starts when main() is called below).
    app_entry = __import__("app_entry")

    # Power-on self-test: framework checks + the guest's optional checks, run
    # BEFORE a candidate may confirm so an unhealthy candidate is rolled back
    # instead of promoted.
    post_result = post.run_post(app_entry)
    post.set_boot_context(is_candidate, post_result)

    if is_candidate and not post_result.ok:
        print("POST failed on candidate %s; rolling back" % slot)
        rollback_candidate(state)
        # A clean reboot drops modules imported by the failed candidate.
        machine.reset()

    if is_candidate:
        # POST passed: promote the candidate now (inside the 12 s window).
        # main() still runs briefly below so a bad main() is caught and rolled
        # back before the watchdog's one clean reset; the guest holds
        # actuation via post.is_candidate_boot().
        confirm_running_slot(slot)
        print("Candidate %s confirmed after POST" % slot)

    try:
        await app_entry.main()
    except Exception as error:
        if not is_candidate:
            raise
        print("Candidate slot %s failed: %s" % (slot, error))
        rollback_candidate(state)
        machine.reset()


if __name__ == "__main__":
    asyncio.run(launch())
