"""On-device automated test runner with a shell command (``test``).

Discovers ``test_*.py`` modules in a device directory (default ``/autotests``,
outside the A/B slots so test code never ships inside a firmware release),
runs them inside the application's own uasyncio loop, and reports per-test
results over the shell. The suites themselves are pushed to the device by the
host tool (``tools/target/autotest.py``); nothing here depends on any
application domain.

Test modules are written against the standard ``unittest`` API. MicroPython
has no ``unittest`` module, so the test directory ships a small compatible
shim (``autotests/unittest.py``, copied to ``/autotests/`` by assembly); the
runner binds that module when it imports each suite, and coroutine test
methods are awaited with a bounded ``wait_for`` -- a live-network test can
never wedge the board or the shell.

Safety rails (this runs inside a live device):
* a per-module heap floor aborts before an allocation can OOM-kill the app;
* a per-test timeout bounds every async test;
* a re-entrancy flag prevents overlapping runs;
* failures are WARN (file-logged, per the flash-wear policy), passes are not.

Shell commands (registered by ``register``):
    test list              discovered modules/cases + current heap
    test run [PATTERN]     run everything (or the subset PATTERN matches)
"""

import gc
import sys
import time

try:
    import io
except ImportError:  # pragma: no cover - MicroPython ships io
    io = None
try:
    import uos as os
except ImportError:  # CPython host tests
    import os
try:
    import uasyncio as asyncio
except ImportError:  # CPython host tests
    import asyncio

__all__ = ["AutoTest", "register"]


def _now_ms():
    try:
        return time.ticks_ms()
    except AttributeError:
        return int(time.monotonic() * 1000)


def _elapsed_ms(start, now):
    try:
        return time.ticks_diff(now, start)
    except AttributeError:
        return now - start


def _mem_free():
    """Free heap bytes; a large constant on hosts (CPython has no mem_free)."""
    try:
        return gc.mem_free()
    except AttributeError:
        return 1 << 30


def _is_coroutine(obj):
    """True for anything awaiting a run: CPython native coroutines AND
    MicroPython ``async def`` results (plain generators WITHOUT __await__ --
    verified on-device: a bare hasattr(x, '__await__') check silently
    discards them, making every async test pass vacuously)."""
    return hasattr(obj, "__await__") or (
        hasattr(obj, "send") and hasattr(obj, "throw")
        and hasattr(obj, "__next__"))


def _format_exc(exc, max_lines):
    """Traceback text (bounded); sys.print_exception on device, else manual."""
    lines = []
    try:
        if io is not None and hasattr(sys, "print_exception"):
            buf = io.StringIO()
            sys.print_exception(exc, buf)
            lines = [ln for ln in buf.getvalue().split("\n") if ln]
        else:
            lines = ["%s: %s" % (type(exc).__name__, exc)]
    except Exception:
        lines = ["%s: %s" % (type(exc).__name__, exc)]
    return lines[-max_lines:] if max_lines else lines


def _isdir(path):
    """Directory probe portable to builds WITHOUT os.path (verified on the
    1.29.0 rp2 build: os.path attribute is missing entirely; os.stat is
    always present and S_IFDIR is 0o40000)."""
    try:
        return bool(os.stat(path)[0] & 0o40000)
    except OSError:
        return False


def resolve_directory(preferred=None):
    """Where suites live, in priority order.

    1. An explicit directory (host tool / embedding app).
    2. ``<slot>/autotests`` -- suites packaged by a --debug OTA build:
       integrity-checked and versioned with the RUNNING firmware (the
       launcher put the slot on sys.path; a later release OTA drops the
       directory away). This authority also makes stale USB-push debris
       under /autotests harmless.
    3. ``/autotests`` -- the USB push target (bench boards without a
       --debug OTA).
    4. The default (so 'test list' reports a useful missing-directory path).
    """
    if preferred:
        return preferred
    for entry in sys.path:
        if not isinstance(entry, str) or not entry:
            continue
        candidate = entry.rstrip("/") + "/autotests"
        if _isdir(candidate):
            return candidate
    if _isdir("/autotests"):
        return "/autotests"
    return "/autotests"


class AutoTest(object):
    """Discover + run ``test_*.py`` suites from a device directory."""

    def __init__(self, directory=None, heap_floor=40000,
                 test_timeout_s=60, max_tb_lines=6, log=None, warn=None):
        self.directory = resolve_directory(directory)
        self.heap_floor = int(heap_floor)
        self.test_timeout_s = float(test_timeout_s)
        self.max_tb_lines = int(max_tb_lines)
        self._log = log            # INFO -> console only
        self._warn = warn if warn is not None else log  # WARN/ERROR -> flash
        self._running = False

    # ------------------------------------------------------------------ shell
    async def handle(self, args=""):
        parts = args.split()
        command = parts[0].lower() if parts else "run"
        if command == "list":
            return self._cmd_list()
        if command == "run":
            pattern = parts[1] if len(parts) > 1 else ""
            return await self._run(pattern)
        return "usage: test list | test run [PATTERN]"

    def _cmd_list(self):
        if self._unittest() is None:
            return "error: cannot import 'unittest' from %s (shim missing?)" \
                % self.directory
        try:
            names = sorted(n for n in os.listdir(self.directory)
                           if n.startswith("test_") and n.endswith(".py"))
        except OSError:
            return ("no test directory at %s (push suites over USB, or OTA a "
                    "--debug build)" % self.directory)
        lines = ["%s: %d modules (heap %d B, floor %d B, timeout %ds)"
                 % (self.directory, len(names), _mem_free(),
                    self.heap_floor, self.test_timeout_s)]
        for name in names:
            module_name = name[:-3]
            cases = "-"
            try:
                module = self._import_module(module_name)
                cases = str(len(self._collect(module, "")))
            except Exception as exc:
                cases = "IMPORT ERROR: %s" % exc
            lines.append("  %s: %s cases" % (module_name, cases))
        return "\n".join(lines)

    # -------------------------------------------------------------- discovery
    def _unittest(self):
        """The unittest module the suites use (device: shim in directory)."""
        if self.directory not in sys.path:
            sys.path.insert(0, self.directory)
        try:
            import unittest
        except ImportError:
            return None
        return unittest

    def _import_module(self, module_name):
        sys.modules.pop(module_name, None)  # always run the freshly pushed code
        return __import__(module_name)

    def _collect(self, module, pattern):
        """[(case_id, class, method_name)] in stable order; PATTERN substring.

        Classes (not instances) are collected so the runner gets a fresh
        instance per test -- like unittest -- and one test cannot leak state
        into the next.
        """
        unittest = self._unittest()
        tests = []
        for cls_name in sorted(dir(module)):
            if not cls_name.startswith("Test"):
                continue
            cls = getattr(module, cls_name)
            if not isinstance(cls, type) or cls is unittest.TestCase:
                continue
            if not issubclass(cls, unittest.TestCase):
                continue
            for meth_name in sorted(dir(cls)):
                if not meth_name.startswith("test_"):
                    continue
                case_id = "%s.%s.%s" % (module.__name__, cls_name, meth_name)
                if pattern and pattern not in case_id:
                    continue
                tests.append((case_id, cls, meth_name))
        return tests

    # -------------------------------------------------------------------- run
    async def _run(self, pattern):
        if self._running:
            return "error: a test run is already in progress"
        if self._unittest() is None:
            return "error: cannot import 'unittest' from %s (shim missing?)" \
                % self.directory
        try:
            names = sorted(n for n in os.listdir(self.directory)
                           if n.startswith("test_") and n.endswith(".py"))
        except OSError:
            return ("no test directory at %s (push suites over USB, or OTA a "
                    "--debug build)" % self.directory)
        self._running = True
        started = _now_ms()
        passed = failed = skipped = 0
        heap_low = _mem_free()
        lines = []
        try:
            for name in names:
                module_name = name[:-3]
                try:
                    module = self._import_module(module_name)
                except Exception as exc:
                    failed += 1
                    lines.append("ERROR %s: import failed" % module_name)
                    lines.extend("  " + ln for ln in
                                 _format_exc(exc, self.max_tb_lines))
                    continue
                tests = self._collect(module, pattern)
                if not tests:
                    continue
                lines.append("-- %s (%d)" % (module_name, len(tests)))
                for case_id, cls, meth_name in tests:
                    outcome, detail, duration = await self._run_one(
                        cls, meth_name)
                    if outcome == "PASS":
                        passed += 1
                    elif outcome == "SKIP":
                        skipped += 1
                    else:
                        failed += 1
                    free = _mem_free()
                    if free < heap_low:
                        heap_low = free
                    suffix = "" if outcome == "PASS" else (
                        ("  " + detail.split("\n")[0]) if detail else "")
                    lines.append("%-5s %s (%d ms)%s"
                                 % (outcome, case_id, duration, suffix))
                    if outcome in ("FAIL", "ERROR") and detail \
                            and "\n" in detail:
                        lines.extend("  " + ln for ln in detail.split("\n"))
        finally:
            self._running = False
            gc.collect()
        total_s = _elapsed_ms(started, _now_ms()) / 1000.0
        summary = ("RESULT: %d passed, %d failed, %d skipped "
                   "(%.1fs, heap_low %d B)"
                   % (passed, failed, skipped, total_s, heap_low))
        lines.append(summary)
        if failed:
            self._warn_log("AutoTest: %s" % summary)
        else:
            self._info_log("AutoTest: %s" % summary)
        return "\n".join(lines)

    async def _run_one(self, cls, meth_name):
        """Execute one test on a fresh instance; (outcome, detail, ms)."""
        started = _now_ms()
        gc.collect()
        free = _mem_free()
        if free < self.heap_floor:
            return ("FAIL", "heap guard: %d B free < floor %d B"
                    % (free, self.heap_floor), 0)
        unittest = self._unittest()
        try:
            instance = cls()
        except Exception as exc:  # a suite that cannot even be constructed
            return ("ERROR", "\n".join(_format_exc(exc, self.max_tb_lines)), 0)
        timeout = float(getattr(instance, "timeout_s", 0)) or self.test_timeout_s
        try:
            await self._maybe_await_hook(instance, "setUp", timeout)
            result = getattr(instance, meth_name)()
            if _is_coroutine(result):
                result = await asyncio.wait_for(result, timeout)
            outcome, detail = "PASS", ""
        except unittest.SkipTest as exc:
            outcome, detail = "SKIP", str(exc)
        except asyncio.TimeoutError:
            outcome = "FAIL"
            detail = "test exceeded its %gs timeout" % timeout
        except Exception as exc:  # includes AssertionError
            outcome = "FAIL" if isinstance(exc, AssertionError) else "ERROR"
            detail = "\n".join(_format_exc(exc, self.max_tb_lines))
        finally:
            try:
                await self._maybe_await_hook(instance, "tearDown", timeout)
            except Exception as exc:
                if outcome == "PASS":
                    outcome, detail = "ERROR", "tearDown: %s" % exc
        duration = _elapsed_ms(started, _now_ms())
        return outcome, detail, duration

    async def _maybe_await_hook(self, instance, name, timeout):
        """Run setUp/tearDown; an async-def hook is awaited like a test."""
        result = getattr(instance, name)()
        if _is_coroutine(result):
            await asyncio.wait_for(result, timeout)

    # ------------------------------------------------------------------ misc
    def _info_log(self, message):
        if self._log:
            self._log(message)

    def _warn_log(self, message):
        if self._warn:
            self._warn(message)


def register(shell, runner=None, **kwargs):
    """Register the ``test`` command on a framework TelnetService."""
    runner = runner if runner is not None else AutoTest(**kwargs)
    shell.add("test", runner.handle,
              "device test suites: list | run [PATTERN]  (%s)"
              % runner.directory)
    return runner
