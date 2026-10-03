import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools" / "target"
MODULE_PATH = TOOLS / "provision.py"


def load_provision():
    sys.path.insert(0, str(TOOLS))
    try:
        spec = importlib.util.spec_from_file_location("provision_under_test", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(TOOLS))


class ProvisionToolTests(unittest.TestCase):
    def setUp(self):
        self.provision = load_provision()

    def test_argument_parser_has_cross_platform_defaults(self):
        args = self.provision.parse_args([])
        self.assertEqual(args.board, "pico2-w")
        self.assertEqual(args.boot_marker, "entering main loop")
        self.assertEqual(args.ip_file, ".micropy-device-ip")
        self.assertEqual(args.shell_port, 23)

    def test_choose_config_prefers_local_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local = root / "system-config.json"
            example = root / "system-config.example.json"
            local.write_text("{}")
            example.write_text("{}")
            self.assertEqual(self.provision.choose_config(root), local.resolve())

    def test_choose_app_config_optional(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(self.provision.choose_app_config(root))
            local = root / "app-config.json"
            local.write_text("{}")
            self.assertEqual(self.provision.choose_app_config(root),
                             local.resolve())

    def test_stage_filters_host_files_and_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "stage"
            source.mkdir()
            (source / "main.py").write_text("pass\n")
            (source / ".micropy-system-device-tree").write_text("marker\n")
            (source / ".DS_Store").write_bytes(b"host")
            cache = source / "__pycache__"
            cache.mkdir()
            (cache / "main.pyc").write_bytes(b"compiled")

            self.provision.stage_device_tree(source, destination)

            self.assertTrue((destination / "main.py").is_file())
            self.assertFalse((destination / ".micropy-system-device-tree").exists())
            self.assertFalse((destination / ".DS_Store").exists())
            self.assertFalse((destination / "__pycache__").exists())

    def test_uf2_copy_is_plain_byte_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "firmware.uf2"
            volume = root / "volume"
            volume.mkdir()
            payload = b"UF2" * 4096
            source.write_bytes(payload)

            self.provision.copy_uf2(source, volume)

            self.assertEqual((volume / source.name).read_bytes(), payload)


if __name__ == "__main__":
    unittest.main()
