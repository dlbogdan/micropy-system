import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "lib" / "coresys" / "manager_tasks.py"


def load_manager_tasks():
    fake_asyncio = types.ModuleType("uasyncio")
    fake_asyncio.create_task = asyncio.create_task
    fake_asyncio.CancelledError = asyncio.CancelledError

    fake_logger = types.ModuleType("lib.coresys.logger")
    fake_logger.debug = lambda *args, **kwargs: None
    fake_logger.error = lambda *args, **kwargs: None
    fake_logger.trace = lambda *args, **kwargs: None
    fake_lib = types.ModuleType("lib")
    fake_lib.__path__ = []
    fake_coresys = types.ModuleType("lib.coresys")
    fake_coresys.__path__ = []
    fake_coresys.logger = fake_logger
    fake_lib.coresys = fake_coresys

    spec = importlib.util.spec_from_file_location("manager_tasks_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {
            "uasyncio": fake_asyncio,
            "lib": fake_lib,
            "lib.coresys": fake_coresys,
            "lib.coresys.logger": fake_logger,
    }):
        spec.loader.exec_module(module)
    return module


class TaskManagerTests(unittest.TestCase):
    def test_one_shot_failure_propagates_by_default(self):
        module = load_manager_tasks()

        async def scenario():
            async def fail():
                raise RuntimeError("boom")

            manager = module.TaskManager()
            task_id = manager.create_task(fail(), task_id="required")
            task = manager._tasks[task_id]
            with self.assertRaisesRegex(RuntimeError, "boom"):
                await task
            self.assertNotIn(task_id, manager.get_all_tasks())

        asyncio.run(scenario())

    def test_optional_one_shot_failure_is_reported_and_contained(self):
        module = load_manager_tasks()

        async def scenario():
            async def fail():
                raise RuntimeError("optional service failed")

            manager = module.TaskManager()
            events = []
            manager.add_listener(events.append)
            task_id = manager.create_task(
                fail(), task_id="optional", propagate_exceptions=False)
            self.assertFalse(
                manager.get_task_info(task_id)["propagate_exceptions"])
            task = manager._tasks[task_id]

            self.assertIsNone(await task)
            self.assertNotIn(task_id, manager.get_all_tasks())
            failures = [event for event in events
                        if event.event_type == module.TaskEvent.TASK_FAILED]
            self.assertEqual(len(failures), 1)
            self.assertEqual(str(failures[0].error), "optional service failed")

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
