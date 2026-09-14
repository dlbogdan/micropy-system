"""Central watchdog ownership for A/B candidate supervision."""

import machine
import uasyncio as asyncio

from lib.coresys.ota_state import load_state


CANDIDATE_TIMEOUT_MS = 8000
FEED_INTERVAL_MS = 1000
CANDIDATE_CONFIRMATION_MS = 12000


class WatchdogOwner:
    """Own the process-wide hardware watchdog and its sole feed loop."""

    def __init__(self, timeout_ms=CANDIDATE_TIMEOUT_MS,
                 feed_interval_ms=FEED_INTERVAL_MS,
                 confirmation_ms=CANDIDATE_CONFIRMATION_MS):
        if feed_interval_ms <= 0 or feed_interval_ms >= timeout_ms:
            raise ValueError("Watchdog feed interval must be below timeout")
        if confirmation_ms <= 0:
            raise ValueError("Candidate confirmation period must be positive")
        self.timeout_ms = timeout_ms
        self.feed_interval_ms = feed_interval_ms
        self.confirmation_ms = confirmation_ms
        self._watchdog = None
        self._feed_task = None
        self._candidate_slot = None

    async def _feed_loop(self):
        watchdog = self._watchdog
        if watchdog is None:
            raise RuntimeError("Watchdog feed loop started without hardware")
        elapsed_ms = 0
        while True:
            state = load_state()
            if (self._candidate_slot is not None and
                    state["pending"] == self._candidate_slot):
                if elapsed_ms >= self.confirmation_ms:
                    print("Candidate confirmation timed out; watchdog will reset")
                    return
            elif (self._candidate_slot is not None and
                  state["active"] == self._candidate_slot):
                # A MicroPython hardware WDT cannot be stopped. Confirmation is
                # already durable, so reboot once to return as an ordinary slot
                # with no watchdog armed and preserve raw-REPL/debugger access.
                print("Candidate confirmed; rebooting without watchdog")
                machine.reset()
                return
            elif self._candidate_slot is not None:
                print("Candidate supervision ended without promotion")
                return
            watchdog.feed()
            await asyncio.sleep(self.feed_interval_ms / 1000)
            elapsed_ms += self.feed_interval_ms

    def start_supervision(self, candidate_slot=None):
        """Start the sole WDT feed task, optionally with a candidate deadline."""
        self._candidate_slot = candidate_slot
        if self._watchdog is None:
            self._watchdog = machine.WDT(timeout=self.timeout_ms)
            self._watchdog.feed()
        elif self._feed_task is not None:
            try:
                if not self._feed_task.done():
                    return self._feed_task
            except AttributeError:
                return self._feed_task
        self._feed_task = asyncio.create_task(self._feed_loop())
        return self._feed_task

    @property
    def active(self):
        return self._watchdog is not None


watchdog_owner = WatchdogOwner()
