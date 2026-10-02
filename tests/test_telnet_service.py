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
