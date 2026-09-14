import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module():
    fake_machine = types.ModuleType("machine")
    fake_machine.WDT = mock.Mock()
    fake_asyncio = types.ModuleType("uasyncio")
    fake_asyncio.create_task = asyncio.create_task
    fake_asyncio.sleep = asyncio.sleep
    fake_state = types.ModuleType("lib.coresys.ota_state")
    fake_state.load_state = mock.Mock(return_value={
        "active": "a", "pending": "b"})
    with mock.patch.dict(sys.modules, {
            "machine": fake_machine, "uasyncio": fake_asyncio,
            "lib.coresys.ota_state": fake_state}):
        spec = importlib.util.spec_from_file_location(
            "watchdog_test", ROOT / "src/lib/coresys/watchdog.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module, fake_machine


class WatchdogTests(unittest.IsolatedAsyncioTestCase):
    async def test_candidate_watchdog_has_one_owner_and_feed_task(self):
        module, machine = load_module()
        hardware_watchdog = mock.Mock()
        machine.WDT.return_value = hardware_watchdog
        owner = module.WatchdogOwner(
            timeout_ms=8000, feed_interval_ms=10,
            confirmation_ms=1000)

        first_task = owner.start_supervision("b")
        second_task = owner.start_supervision("b")
        await asyncio.sleep(0.025)

        self.assertTrue(owner.active)
        self.assertIs(first_task, second_task)
        machine.WDT.assert_called_once_with(timeout=8000)
        self.assertGreaterEqual(hardware_watchdog.feed.call_count, 2)
        first_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first_task

    async def test_unconfirmed_candidate_stops_feeding_after_deadline(self):
        module, machine = load_module()
        hardware_watchdog = mock.Mock()
        machine.WDT.return_value = hardware_watchdog
        owner = module.WatchdogOwner(
            timeout_ms=8000, feed_interval_ms=1, confirmation_ms=2)

        task = owner.start_supervision("b")
        await task

        self.assertEqual(hardware_watchdog.feed.call_count, 3)

    async def test_confirmed_candidate_continues_feeding(self):
        module, machine = load_module()
        module.load_state.return_value = {"active": "b", "pending": None}
        hardware_watchdog = mock.Mock()
        machine.WDT.return_value = hardware_watchdog
        owner = module.WatchdogOwner(
            timeout_ms=8000, feed_interval_ms=5, confirmation_ms=5)

        task = owner.start_supervision("b")
        await asyncio.sleep(0.016)

        self.assertFalse(task.done())
        self.assertGreaterEqual(hardware_watchdog.feed.call_count, 3)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_normal_boot_feeds_watchdog_without_candidate_deadline(self):
        module, machine = load_module()
        module.load_state.return_value = {"active": "a", "pending": None}
        hardware_watchdog = mock.Mock()
        machine.WDT.return_value = hardware_watchdog
        owner = module.WatchdogOwner(
            timeout_ms=8000, feed_interval_ms=2, confirmation_ms=2)

        task = owner.start_supervision()
        await asyncio.sleep(0.008)

        self.assertFalse(task.done())
        self.assertGreaterEqual(hardware_watchdog.feed.call_count, 3)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_feed_interval_must_be_less_than_timeout(self):
        module, _ = load_module()
        with self.assertRaises(ValueError):
            module.WatchdogOwner(timeout_ms=1000, feed_interval_ms=1000)


if __name__ == "__main__":
    unittest.main()
