import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "lib" / "coresys" / "telnet_service.py"


def load_telnet_service():
    fake_asyncio = types.ModuleType("uasyncio")
    fake_json = types.ModuleType("ujson")
    fake_json.dumps = json.dumps
    fake_machine = types.ModuleType("machine")
    fake_machine.reset = lambda: None
    fake_logger = types.ModuleType("lib.coresys.logger")
    fake_logger.info = lambda *args, **kwargs: None
    fake_logger.error = lambda *args, **kwargs: None
    fake_ota_state = types.ModuleType("lib.coresys.ota_state")
    fake_ota_state.load_state = lambda: {}
    fake_lib = types.ModuleType("lib")
    fake_lib.__path__ = []
    fake_coresys = types.ModuleType("lib.coresys")
    fake_coresys.__path__ = []
    fake_coresys.logger = fake_logger
    fake_coresys.ota_state = fake_ota_state
    fake_lib.coresys = fake_coresys

    spec = importlib.util.spec_from_file_location("telnet_service_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {
            "uasyncio": fake_asyncio,
            "ujson": fake_json,
            "machine": fake_machine,
            "lib": fake_lib,
            "lib.coresys": fake_coresys,
            "lib.coresys.logger": fake_logger,
            "lib.coresys.ota_state": fake_ota_state,
    }):
        spec.loader.exec_module(module)
    return module


class _Reader:
    def __init__(self, lines):
        self.lines = list(lines)

    async def readline(self):
        return self.lines.pop(0) if self.lines else b""


class _Writer:
    def __init__(self):
        self.output = bytearray()
        self.closed = False

    def write(self, data):
        self.output.extend(data)

    async def drain(self):
        return None

    def close(self):
        self.closed = True


class TelnetServiceTests(unittest.TestCase):
    def test_busy_connection_is_rejected_without_clearing_flag(self):
        module = load_telnet_service()
        service = module.TelnetService()
        service._busy = True  # an active client owns the flag
        reader = _Reader([b"status\n"])
        writer = _Writer()

        asyncio.run(service._handle(reader, writer))

        self.assertIn("busy: one client at a time", writer.output.decode())
        self.assertTrue(writer.closed)
        self.assertTrue(service._busy)  # still owned by the active client

    def test_repl_is_disabled_by_default(self):
        module = load_telnet_service()
        service = module.TelnetService()
        self.assertNotIn("repl", service._help(""))

        reader = _Reader([b"repl\n", b"quit\n"])
        writer = _Writer()
        asyncio.run(service._handle(reader, writer))

        self.assertIn("repl disabled\n%s\n" % module.END_MARKER,
                      writer.output.decode())
        self.assertTrue(writer.closed)

    def test_repl_can_be_explicitly_enabled(self):
        module = load_telnet_service()
        service = module.TelnetService(allow_repl=True)
        self.assertIn("repl", service._help(""))

    def test_async_handler_is_awaited(self):
        # App handlers may be coroutines (async I/O that must not block the
        # board); the service must await them and return the result.
        module = load_telnet_service()
        service = module.TelnetService()

        async def async_handler(_arg=""):
            await asyncio.sleep(0)
            return "async-result:42"

        service.add("mycmd", async_handler, "an async command")

        reader = _Reader([b"mycmd\n"])
        writer = _Writer()
        asyncio.run(service._handle(reader, writer))

        self.assertIn("async-result:42", writer.output.decode())

    def test_micropython_style_coroutine_is_awaited(self):
        # MicroPython coroutines are plain generators WITHOUT __await__
        # (verified on-device: an async handler returned a bare
        # '<generator object>' string). Simulate that shape on the host.
        module = load_telnet_service()
        service = module.TelnetService()

        def mp_coroutine(_arg=""):
            yield  # a generator: no native-coroutine attributes
            return "mp-async:7"

        class NoAwait:
            """Device-shape stand-in: exposes the generator protocol.

            MicroPython awaits such objects natively; on the host CPython
            still needs __await__ to drive the loop, so return the generator
            (the behavior under test is the DETECTION, not CPython's await).
            """

            def __init__(self, gen):
                self._gen = gen

            def send(self, value):
                return self._gen.send(value)

            def throw(self, *args):
                return self._gen.throw(*args)

            def __next__(self):
                return next(self._gen)

            def __await__(self):
                return self._gen

        def handler(arg=""):
            return NoAwait(mp_coroutine(arg))

        service.add("mpcmd", handler, "mp-style async command")
        reader = _Reader([b"mpcmd\n"])
        writer = _Writer()
        asyncio.run(service._handle(reader, writer))
        self.assertIn("mp-async:7", writer.output.decode())

    def test_async_handler_error_is_reported(self):
        # A failing async handler reports the error instead of dropping the
        # connection.
        module = load_telnet_service()
        service = module.TelnetService()

        async def failing_handler(_arg=""):
            await asyncio.sleep(0)
            raise RuntimeError("boom")

        service.add("mycmd", failing_handler, "an async command")

        reader = _Reader([b"mycmd\n"])
        writer = _Writer()
        asyncio.run(service._handle(reader, writer))

        self.assertIn("error: boom", writer.output.decode())

    def test_auth_token_gates_all_commands(self):
        module = load_telnet_service()
        service = module.TelnetService(auth_token="secret")
        reader = _Reader([
            b"auth wrong\n",
            b"help\n",
            b"auth secret\n",
            b"help\n",
            b"quit\n",
        ])
        writer = _Writer()

        asyncio.run(service._handle(reader, writer))

        output = writer.output.decode()
        self.assertIn("Authentication required: auth TOKEN", output)
        self.assertEqual(output.count("authentication required\n"), 2)
        self.assertIn("authenticated\n", output)
        self.assertIn("status    one-line JSON", output)


class StreamingHandlerTests(unittest.TestCase):
    """Handlers that take (args, emit) stream progress lines; 1-arg
    handlers keep the buffered reply. The arity probe must never
    double-invoke a handler (binding errors precede side effects)."""

    def test_wants_emit_arity_probe(self):
        module = load_telnet_service()
        wants = module.TelnetService._wants_emit

        def one_arg(_args=""):
            return ""

        def two_args(_args="", _emit=None):
            return ""

        class Holder:
            def buffered(self, _args=""):
                return ""

            def streaming(self, _args="", _emit=None):
                return ""

        holder = Holder()
        self.assertFalse(wants(one_arg))
        self.assertTrue(wants(two_args))
        self.assertFalse(wants(holder.buffered))   # self discounted
        self.assertTrue(wants(holder.streaming))
        self.assertFalse(wants(object()))          # no code object

    def test_wants_emit_bound_shape_via_dunder_func(self):
        # The probe resolves CPython-style bound methods through __func__
        # (and discounts self). NB: the REAL MicroPython bound shape has
        # no __code__/__func__/__self__ at all -- verified on-device --
        # which the opaque-flag test below covers.
        module = load_telnet_service()
        wants = module.TelnetService._wants_emit

        def streaming(_self, _args="", _emit=None):
            return ""

        def buffered(_self, _args=""):
            return ""

        class MpBound:  # mp shape: only __func__ + __self__, no __code__
            pass

        holder = MpBound()
        stream = MpBound()
        stream.__func__, stream.__self__ = streaming, holder
        plain = MpBound()
        plain.__func__, plain.__self__ = buffered, holder
        self.assertTrue(wants(stream))
        self.assertFalse(wants(plain))

    def test_streaming_handler_lines_arrive_before_end(self):
        module = load_telnet_service()
        service = module.TelnetService()

        async def streaming_handler(_arg="", emit=None):
            await emit("step 1")
            await emit("step 2")
            return None  # streamed everything: nothing left to bulk-write

        service.add("walk", streaming_handler, "streams progress")
        reader = _Reader([b"walk\n"])
        writer = _Writer()

        asyncio.run(service._handle(reader, writer))

        output = writer.output.decode()
        self.assertIn("step 1\nstep 2\n", output)
        self.assertTrue(output.endswith("%s\n" % module.END_MARKER))
        # No stray blank line between the streamed lines and END.
        self.assertNotIn("step 2\n\n%s" % module.END_MARKER, output)

    def test_one_arg_handler_keeps_buffered_reply(self):
        module = load_telnet_service()
        service = module.TelnetService()

        def buffered(_arg=""):
            return "buffered-reply"

        service.add("old", buffered, "classic handler")
        reader = _Reader([b"old\n"])
        writer = _Writer()

        asyncio.run(service._handle(reader, writer))

        output = writer.output.decode()
        self.assertIn("buffered-reply\n%s\n" % module.END_MARKER, output)

    def test_streaming_flag_streams_without_introspectable_handler(self):
        # Device reality pin (verified on the Pico 2 W): MicroPython bound
        # methods expose NO __code__, __func__ or __self__ -- the arity
        # probe cannot work there. The explicit streaming=True flag on
        # add() is what activates the emit path.
        module = load_telnet_service()
        service = module.TelnetService()

        class MpOpaque:  # callable, zero introspection attributes
            def __call__(self, _args="", emit=None):
                return self._run(_args, emit)

            async def _run(self, _args, emit):
                await emit("mp-step 1")
                await emit("mp-step 2")
                return None

        handler = MpOpaque()
        self.assertIsNone(getattr(handler, "__code__", None))
        service.add("mpwalk", handler, "opaque streaming", streaming=True)
        reader = _Reader([b"mpwalk\n"])
        writer = _Writer()

        asyncio.run(service._handle(reader, writer))

        output = writer.output.decode()
        self.assertIn("mp-step 1\nmp-step 2\n", output)
        self.assertTrue(output.endswith("%s\n" % module.END_MARKER))


if __name__ == "__main__":
    unittest.main()
