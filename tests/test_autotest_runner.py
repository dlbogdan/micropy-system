"""Host tests for the on-device test runner (lib/coresys/autotest.py).

The runner must behave identically in the device loop and on a host (the
directory points at a temp tree here). These tests pin the smart parts:
discovery order, PATTERN filtering, fresh instance per test, async tests
awaited + bounded by timeout, heap guard, SKIP/FAIL/ERROR classification,
import-failure isolation, and the re-entrancy guard.
"""

import asyncio
import importlib.util
import re
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "lib" / "coresys" / "autotest.py"


def load_autotest():
    """Import the device module on the host (its uos/uasyncio fallbacks)."""
    spec = importlib.util.spec_from_file_location("autotest_under_test",
                                                  MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    saved = sys.modules.pop("uos", None)  # force the os fallback
    try:
        spec.loader.exec_module(module)
    finally:
        if saved is not None:
            sys.modules["uos"] = saved
    return module


SUITE_OK = '''
import asyncio
import unittest


class TestAlpha(unittest.TestCase):
    def test_sync_pass(self):
        self.assertEqual(1 + 1, 2)

    async def test_async_pass(self):
        await asyncio.sleep(0)
        self.assertTrue(True)

    def test_skipped(self):
        self.skipTest("not today")

    async def test_slow(self):
        await asyncio.sleep(5)  # exceeds the 0.05 s default used here

    def test_fresh_instance(self):
        # An attribute set by a previous test must not leak into this one.
        self.assertFalse(hasattr(self, "poison"))

    def test_poisons(self):
        self.poison = True


class TestNotACase(object):
    def test_ignored(self):
        raise AssertionError("never collected")
'''

SUITE_FAILS = '''
import unittest


class TestBroken(unittest.TestCase):
    def test_assertion(self):
        self.assertEqual(1, 2, "boom")

    def test_raises(self):
        raise RuntimeError("kaboom")
'''

SUITE_BROKEN_IMPORT = '''
import totally_missing_module  # noqa

import unittest


class TestNever(unittest.TestCase):
    def test_never(self):
        pass
'''

SUITE_TIMEOUT_OVERRIDE = '''
import asyncio
import unittest


class TestPatient(unittest.TestCase):
    timeout_s = 10  # beats the runner default (0.05 s here)

    async def test_within_override(self):
        await asyncio.sleep(0.2)
'''

SUITE_ASYNC_SETUP = '''
import asyncio
import unittest


class TestAsyncHook(unittest.TestCase):
    async def setUp(self):
        await asyncio.sleep(0)
        self.ready = True

    async def test_setup_ran(self):
        self.assertTrue(self.ready)

    async def tearDown(self):
        await asyncio.sleep(0)


class TestAsyncSetupFails(unittest.TestCase):
    async def setUp(self):
        raise RuntimeError("setup exploded")

    def test_never_runs(self):
        self.fail("must not run")
'''

SUITES = {
    "test_alpha.py": SUITE_OK,
    "test_fails.py": SUITE_FAILS,
    "test_broken.py": SUITE_BROKEN_IMPORT,
    "test_timeout_override.py": SUITE_TIMEOUT_OVERRIDE,
    "test_async_setup.py": SUITE_ASYNC_SETUP,
}


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.module = load_autotest()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "test_alpha.py").write_text(SUITE_OK)
        self.addCleanup(self.tmp.cleanup)
        # Suites land in sys.modules under bare names; keep tests isolated.
        self.addCleanup(lambda: [sys.modules.pop(n, None) for n in SUITES])

    def _write(self, name):
        (self.dir / name).write_text(SUITES[name])

    def _runner(self, **kwargs):
        kwargs.setdefault("heap_floor", 0)      # host heap != MicroPython
        kwargs.setdefault("test_timeout_s", 0.05)
        return self.module.AutoTest(directory=str(self.dir), **kwargs)

    def _run(self, runner, pattern=""):
        return asyncio.run(runner._run(pattern))

    def test_happy_suite_passes_skip_and_timeout(self):
        text = self._run(self._runner())
        self.assertIn("PASS  test_alpha.TestAlpha.test_sync_pass", text)
        self.assertIn("PASS  test_alpha.TestAlpha.test_async_pass", text)
        self.assertIn("SKIP  test_alpha.TestAlpha.test_skipped", text)
        self.assertIn("FAIL  test_alpha.TestAlpha.test_slow", text)
        self.assertIn("timeout", text)
        # Fresh instance per test: no state leaked from test_poisons.
        self.assertIn("PASS  test_alpha.TestAlpha.test_fresh_instance", text)
        summary = re.search(r"RESULT: (\d+) passed, (\d+) failed, (\d+) skipped",
                            text)
        self.assertEqual(summary.groups(), ("4", "1", "1"))

    def test_pattern_filters_cases(self):
        text = self._run(self._runner(), pattern="test_sync_pass")
        self.assertIn("PASS  test_alpha.TestAlpha.test_sync_pass", text)
        self.assertNotIn("test_async_pass", text)

    def test_failures_and_errors_classified(self):
        self._write("test_fails.py")
        text = self._run(self._runner())
        self.assertIn("FAIL  test_fails.TestBroken.test_assertion", text)
        self.assertIn("boom", text)            # assertion message surfaces
        self.assertIn("ERROR test_fails.TestBroken.test_raises", text)
        self.assertIn("kaboom", text)

    def test_import_failure_isolated_to_its_module(self):
        self._write("test_broken.py")
        text = self._run(self._runner())
        self.assertIn("ERROR test_broken: import failed", text)
        self.assertIn("RESULT: 4 passed, 2 failed", text)  # alpha unaffected

    def test_heap_guard_aborts_before_running(self):
        text = self._run(self._runner(heap_floor=1 << 40))
        self.assertIn("heap guard", text)

    def test_per_class_timeout_s_overrides_default(self):
        self._write("test_timeout_override.py")
        text = self._run(self._runner())
        self.assertIn("PASS  test_timeout_override.TestPatient"
                      ".test_within_override", text)

    def test_async_setup_teardown_hooks_are_awaited(self):
        # I/O suites need a bounded, awaited setUp (e.g. wait for Wi-Fi);
        # an async-def hook must run like a test, and its failure must be
        # attributed to the test instead of silently skipping it.
        self._write("test_async_setup.py")
        text = self._run(self._runner())
        self.assertIn("PASS  test_async_setup.TestAsyncHook.test_setup_ran",
                      text)
        self.assertIn("ERROR test_async_setup.TestAsyncSetupFails"
                      ".test_never_runs", text)

    def test_reentrancy_guard(self):
        runner = self._runner()
        runner._running = True
        text = asyncio.run(runner._run(""))
        self.assertIn("already in progress", text)

    def test_is_coroutine_detects_micropython_shape(self):
        # Regression pin: MicroPython async-def results are plain generators
        # WITHOUT __await__; the old hasattr(x, '__await__') check discarded
        # them and every async test passed VACUOUSLY (24 ms "passes" for
        # multi-second I/O was the tell).
        pred = self.module._is_coroutine

        async def native():
            return 1

        def plain_gen():
            yield

        class MpCoroutine:  # send/throw/__next__, deliberately no __await__
            def send(self, _):
                raise StopIteration

            def throw(self, *args):
                raise StopIteration

            def __next__(self):
                raise StopIteration

        self.assertTrue(pred(native()))
        self.assertTrue(pred(plain_gen()))
        self.assertTrue(pred(MpCoroutine()))
        self.assertFalse(pred(None))
        self.assertFalse(pred(42))
        self.assertFalse(pred("string"))

    def test_missing_directory_reports_helpfully(self):
        runner = self.module.AutoTest(directory="/nonexistent-tests-dir",
                                      heap_floor=0)
        text = asyncio.run(runner._run(""))
        self.assertIn("no test directory", text)

    def test_resolve_directory_explicit_wins(self):
        self.assertEqual(self.module.resolve_directory("/explicit"),
                         "/explicit")

    def test_resolve_directory_finds_slot_packaged_suites(self):
        # --debug OTA: suites live at <slot>/autotests and the launcher put
        # the slot on sys.path; on hosts /autotests does not exist, so the
        # sys.path scan must find the slot candidate.
        import os
        if os.path.isdir("/autotests"):
            self.skipTest("/autotests exists on this host")
        slot = self.dir / "apps_b"
        (slot / "autotests").mkdir(parents=True)
        saved = list(sys.path)
        try:
            sys.path.insert(0, str(slot))
            self.assertEqual(self.module.resolve_directory(),
                             str(slot) + "/autotests")
        finally:
            sys.path[:] = saved

    def test_resolve_directory_defaults_when_nothing_found(self):
        import os
        if os.path.isdir("/autotests"):
            self.skipTest("/autotests exists on this host")
        saved = list(sys.path)
        try:
            sys.path[:] = [p for p in sys.path
                           if not os.path.isdir(str(p).rstrip("/")
                                                + "/autotests")]
            self.assertEqual(self.module.resolve_directory(), "/autotests")
        finally:
            sys.path[:] = saved

    def test_isdir_probe_needs_no_os_path(self):
        # The device build has no os.path at all (killed the 1.1.77
        # candidate); the stat-bit probe must work for dirs, files, and
        # missing paths.
        (self.dir / "plain_file.py").write_text("x = 1\n")
        (self.dir / "adir").mkdir()
        self.assertTrue(self.module._isdir(str(self.dir / "adir")))
        self.assertFalse(self.module._isdir(str(self.dir / "plain_file.py")))
        self.assertFalse(self.module._isdir(str(self.dir / "missing")))

    def test_resolve_directory_slot_wins_over_push_debris(self):
        # The integrity-checked OTA artifact outranks an unverified stale
        # /autotests (USB-push debris from an older era must not shadow
        # the suites that shipped with the running firmware).
        slot = self.dir / "apps_a"
        (slot / "autotests").mkdir(parents=True)
        saved = list(sys.path)
        real_isdir = self.module._isdir
        try:
            sys.path.insert(0, str(slot))
            self.module._isdir = (
                lambda p: True if p == "/autotests" else real_isdir(p))
            self.assertEqual(self.module.resolve_directory(),
                             str(slot) + "/autotests")
        finally:
            self.module._isdir = real_isdir
            sys.path[:] = saved

    def test_shell_dispatch_and_list(self):
        runner = self._runner()
        text = asyncio.run(runner.handle("list"))
        self.assertIn("test_alpha", text)
        self.assertIn("6 cases", text)  # discovery counts through the classes
        text = asyncio.run(runner.handle("bogus"))
        self.assertIn("usage:", text)

    def test_register_adds_the_test_command(self):
        class FakeShell:
            def __init__(self):
                self.commands = {}

            def add(self, name, handler, description=""):
                self.commands[name] = (handler, description)

        shell = FakeShell()
        runner = self.module.AutoTest(directory=str(self.dir), heap_floor=0)
        returned = self.module.register(shell, runner)
        self.assertIs(returned, runner)
        self.assertIn("test", shell.commands)
        self.assertEqual(shell.commands["test"][0], runner.handle)


if __name__ == "__main__":
    unittest.main()
