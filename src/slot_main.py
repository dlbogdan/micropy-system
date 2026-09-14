"""Stable root launcher installed as /main.py by A/B project assembly."""

import uasyncio as asyncio

from lib.coresys.slot_manager import (
    activate_slot_path,
    prepare_slot_boot,
    rollback_candidate,
)


async def launch():
    slot, is_candidate, state = prepare_slot_boot()
    activate_slot_path(slot)
    try:
        app_entry = __import__("app_entry")
        await app_entry.main()
    except Exception as error:
        if not is_candidate:
            raise
        print("Candidate slot %s failed: %s" % (slot, error))
        rollback_candidate(state)
        # A clean reboot prevents modules partially imported by the failed
        # candidate from contaminating the previous slot process.
        import machine
        machine.reset()


if __name__ == "__main__":
    asyncio.run(launch())
