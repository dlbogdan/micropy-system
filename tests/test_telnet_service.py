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
    fake_logger.clear_log = lambda: True
    fake_logger.clear_error_log = lambda: None
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

    def test_log_clear_reports_success(self):
        # `log clear` truncates the log (via logger.clear_log) and reports OK.
        module = load_telnet_service()
        service = module.TelnetService()
        self.assertIn("OK: log cleared", service._log("clear"))

    def test_log_clear_is_case_insensitive_and_in_help(self):
        module = load_telnet_service()
        service = module.TelnetService()
        self.assertIn("OK: log cleared", service._log("CLEAR"))
        self.assertIn("log clear", service._help(""))

    def test_log_numeric_tail_still_works(self):
        # Adding the `clear` subcommand must not break `log [N]`.
        import tempfile
        module = load_telnet_service()
        service = module.TelnetService()
        with tempfile.NamedTemporaryFile("w", delete=False) as fh:
            for i in range(10):
                fh.write("line %d\n" % i)
            path = fh.name
        service.log_path = path
        try:
            result = service._log("3")
            self.assertIn("line 9", result)
            self.assertIn("line 8", result)
            self.assertIn("line 7", result)
            self.assertNotIn("line 6", result)
        finally:
            import os as _os
            _os.remove(path)

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


if __name__ == "__main__":
    unittest.main()
