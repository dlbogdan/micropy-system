import importlib.util
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "tooling.py"


def load_tooling():
    spec = importlib.util.spec_from_file_location("tooling_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ToolingTests(unittest.TestCase):
    def setUp(self):
        self.tooling = load_tooling()

    def test_app_root_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            explicit = Path(directory) / "explicit"
            environment = Path(directory) / "environment"
            explicit.mkdir()
            environment.mkdir()
            with mock.patch.dict(os.environ, {"MICROPY_APP_ROOT": str(environment)}):
                self.assertEqual(self.tooling.resolve_app_root(explicit), explicit.resolve())
                self.assertEqual(self.tooling.resolve_app_root(), environment.resolve())

    def test_boot_volume_candidates_cover_macos_and_linux(self):
        mac = [str(path) for path in self.tooling.boot_volume_candidates("Darwin")]
        linux = [str(path) for path in
                 self.tooling.boot_volume_candidates("Linux", home="/home/alice")]
        self.assertIn("/Volumes/RPI-RP2", mac)
        self.assertIn("/Volumes/RP2350", mac)
        self.assertIn("/media/alice/RPI-RP2", linux)
        self.assertIn("/run/media/alice/RP2350", linux)

    def test_find_boot_volume_accepts_linux_mountpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            volume = Path(directory) / "RP2350"
            volume.mkdir()
            with mock.patch.object(self.tooling, "_linux_lsblk_mounts",
                                   return_value=[str(volume)]):
                self.assertEqual(
                    self.tooling.find_boot_volume("Linux", candidates=[]),
                    volume.resolve())

    def test_serial_fallbacks_include_linux_devices(self):
        with mock.patch.object(self.tooling.glob, "glob") as glob_mock:
            glob_mock.side_effect = lambda pattern: (
                ["/dev/ttyACM0"] if pattern == "/dev/ttyACM*" else [])
            with mock.patch.dict("sys.modules", {"serial.tools": None}):
                self.assertIn("/dev/ttyACM0", self.tooling.serial_ports())

    def test_serial_detection_ignores_non_usb_ports(self):
        fake_serial = types.ModuleType("serial")
        fake_tools = types.ModuleType("serial.tools")
        fake_list_ports = types.ModuleType("serial.tools.list_ports")
        fake_list_ports.comports = lambda: [
            types.SimpleNamespace(device="/dev/cu.Bluetooth-Incoming-Port", vid=None),
            types.SimpleNamespace(device="/dev/cu.usbmodem1", vid=0x2E8A),
        ]
        fake_tools.list_ports = fake_list_ports
        fake_serial.tools = fake_tools
        with mock.patch.dict("sys.modules", {
                "serial": fake_serial,
                "serial.tools": fake_tools,
                "serial.tools.list_ports": fake_list_ports,
        }), mock.patch.object(self.tooling.glob, "glob", return_value=[]):
            self.assertEqual(self.tooling.serial_ports(), ["/dev/cu.usbmodem1"])


if __name__ == "__main__":
    unittest.main()
