import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
MODULE_PATH = TOOLS / "deploy.py"


def load_deploy():
    sys.path.insert(0, str(TOOLS))
    try:
        spec = importlib.util.spec_from_file_location("deploy_under_test", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(TOOLS))


class DeployToolTests(unittest.TestCase):
    def setUp(self):
        self.deploy = load_deploy()

    def test_patch_version_bump(self):
        self.assertEqual(self.deploy.next_patch("1.2.9\n"), "1.2.10")
        with self.assertRaises(ValueError):
            self.deploy.next_patch("1.2")

    def test_status_parser(self):
        payload = ('{"version":"1.2.3","slot":{"active":"b",'
                   '"pending":null,"rejected":null}}')
        self.assertEqual(
            self.deploy.parse_status(payload), ("1.2.3", "b", None))
        self.assertIsNone(self.deploy.parse_status("not-json"))

    def test_parser_preserves_existing_cli(self):
        args = self.deploy.parse_args([
            "1.2.3", "--usb", "--port", "9000", "--shell-port", "2323",
            "--ip-file", ".device-ip",
        ])
        self.assertEqual(args.version, "1.2.3")
        self.assertTrue(args.usb)
        self.assertEqual(args.port, 9000)
        self.assertEqual(args.shell_port, 2323)
        self.assertEqual(args.ip_file, ".device-ip")


if __name__ == "__main__":
    unittest.main()
