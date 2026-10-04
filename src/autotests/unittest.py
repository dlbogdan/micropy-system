"""Minimal ``unittest``-compatible shim for on-device suites.

MicroPython has no ``unittest`` module. The device test runner
(``lib.coresys.autotest``) binds this module when it imports suites from
``/autotests``, so tests are written against the standard API and the SAME
suite files also run under real ``unittest`` on a host (where this file is
simply shadowed by the stdlib).

Supported: ``TestCase`` with setUp/tearDown and the assert methods below,
``SkipTest``, and ``expectedFailure`` is NOT supported (raise
:class:`SkipTest` instead). ``main()`` exists only to fail loudly if a suite
is ever executed directly -- the runner drives the tests.
"""


class SkipTest(Exception):
    """Raise inside a test to report it as skipped instead of run."""


# NB: assert methods raise the BUILTIN AssertionError (MicroPython ships it);
# the runner uses it to tell FAIL (assertion) from ERROR (unexpected raise).


class TestCase(object):
    """Base class: assert methods only; the autotest runner drives the run."""

    def __init__(self):
        self._skipped = None

    # -- lifecycle -------------------------------------------------------------
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def skipTest(self, reason=""):  # noqa: N802 - unittest spelling
        raise SkipTest(reason)

    # -- assertions ------------------------------------------------------------
    def fail(self, message="failed"):
        raise AssertionError(message)

    def assertTrue(self, expr, message=None):  # noqa: N802
        if not expr:
            self.fail(message or "expected true, got %r" % (expr,))

    def assertFalse(self, expr, message=None):  # noqa: N802
        if expr:
            self.fail(message or "expected false, got %r" % (expr,))

    def assertIs(self, a, b, message=None):  # noqa: N802
        if a is not b:
            self.fail(message or "%r is not %r" % (a, b))

    def assertIsNot(self, a, b, message=None):  # noqa: N802
        if a is b:
            self.fail(message or "unexpectedly identical: %r" % (a,))

    def assertIsNone(self, expr, message=None):  # noqa: N802
        if expr is not None:
            self.fail(message or "expected None, got %r" % (expr,))

    def assertIsNotNone(self, expr, message=None):  # noqa: N802
        if expr is None:
            self.fail(message or "unexpectedly None")

    def assertIsInstance(self, obj, cls, message=None):  # noqa: N802
        if not isinstance(obj, cls):
            self.fail(message or "%r is not an instance of %r" % (obj, cls))

    def assertNotIsInstance(self, obj, cls, message=None):  # noqa: N802
        if isinstance(obj, cls):
            self.fail(message or "%r is unexpectedly an instance of %r"
                      % (obj, cls))

    def assertEqual(self, first, second, message=None):  # noqa: N802
        if first != second:
            self.fail(message or "%r != %r" % (first, second))

    def assertNotEqual(self, first, second, message=None):  # noqa: N802
        if first == second:
            self.fail(message or "unexpectedly equal: %r" % (first,))

    def assertIn(self, member, container, message=None):  # noqa: N802
        if member not in container:
            self.fail(message or "%r not in container" % (member,))

    def assertNotIn(self, member, container, message=None):  # noqa: N802
        if member in container:
            self.fail(message or "%r unexpectedly in container" % (member,))

    def assertAlmostEqual(self, first, second, places=7,  # noqa: N802
                          message=None):
        if abs(first - second) > 10 ** -places / 2:
            self.fail(message or "%r != %r within %d places"
                      % (first, second, places))

    def assertGreater(self, first, second, message=None):  # noqa: N802
        if not first > second:
            self.fail(message or "%r not greater than %r" % (first, second))

    def assertGreaterEqual(self, first, second, message=None):  # noqa: N802
        if not first >= second:
            self.fail(message or "%r not >= %r" % (first, second))

    def assertLess(self, first, second, message=None):  # noqa: N802
        if not first < second:
            self.fail(message or "%r not less than %r" % (first, second))

    def assertLessEqual(self, first, second, message=None):  # noqa: N802
        if not first <= second:
            self.fail(message or "%r not <= %r" % (first, second))

    class _RaisesCtx(object):
        def __init__(self, test, exceptions):
            self._test = test
            self._exceptions = exceptions
            self.exc = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            if exc_type is None:
                self._test.fail("no exception raised (expected %s)"
                                % (self._exceptions,))
            if not issubclass(exc_type, self._exceptions):
                return False  # wrong type: propagate for the real traceback
            self.exc = exc
            return True  # right type: consumed, the assert passes

    def assertRaises(self, *exceptions):  # noqa: N802
        """Context form: ``with self.assertRaises(ValueError): ...``."""
        if len(exceptions) == 1 and callable(exceptions[0]) \
                and not (isinstance(exceptions[0], type)
                         and issubclass(exceptions[0], BaseException)):
            raise NotImplementedError(
                "unittest shim: call form unsupported, use the context form")
        return TestCase._RaisesCtx(self, exceptions)


def main(*args, **kwargs):
    raise RuntimeError(
        "unittest shim: run suites via the device 'test' shell command "
        "(lib.coresys.autotest), not unittest.main()")
