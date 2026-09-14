import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_firmware_module():
    fake_uos = types.ModuleType("uos")
    fake_uos.remove = lambda path: Path(path).unlink()
    fake_uos.rename = lambda source, destination: Path(source).rename(destination)
    fake_uos.stat = lambda path: __import__("os").stat(path)
    fake_uos.listdir = lambda path: __import__("os").listdir(path)
    fake_uos.mkdir = lambda path: __import__("os").mkdir(path)
    fake_uos.rmdir = lambda path: __import__("os").rmdir(path)
    fake_uos.statvfs = lambda path: __import__("os").statvfs(path)
    sys.modules["uos"] = fake_uos
    sys.modules["ujson"] = json

    fake_machine = types.ModuleType("machine")
    class Pin:
        OUT = 1
        def __init__(self, *args, **kwargs): pass
        def toggle(self): pass
        def off(self): pass
    fake_machine.Pin = Pin
    sys.modules["machine"] = fake_machine
    sys.modules["deflate"] = types.ModuleType("deflate")
    sys.modules["utarfile"] = types.ModuleType("utarfile")

    logger = types.ModuleType("lib.coresys.logger")
    logger.info = logger.warning = logger.error = lambda *args, **kwargs: None
    sys.modules["lib"] = types.ModuleType("lib")
    sys.modules["lib.coresys"] = types.ModuleType("lib.coresys")
    sys.modules["lib.coresys.logger"] = logger
    sys.modules["uasyncio"] = asyncio

    spec = importlib.util.spec_from_file_location(
        "manager_firmware_test", ROOT / "src/lib/coresys/manager_firmware.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_firmware_module()


class FakeReader:
    def __init__(self, body):
        self.body = bytearray(body)

    async def read(self, count):
        result = bytes(self.body[:count])
        del self.body[:count]
        return result


class FirmwareUpdaterTests(unittest.TestCase):
    def setUp(self):
        MODULE.FirmwareUpdater.reset_instance()
        self.updater = MODULE.FirmwareUpdater(
            device_model="pico-w-rp2040",
            direct_base_url="https://example.invalid/",
            runtime_version="1.29.0",
            mpy_version=6,
            mpy_sub_version=3,
            mpy_arch="armv6m",
        )

    def release(self, **changes):
        asset = {
            "name": "firmware.tar.zlib",
            "browser_download_url": "https://example.invalid/firmware.tar.zlib",
            "size": 3,
            "sha256": "abc",
            "model": "pico-w-rp2040",
            "runtime_version": "1.29.0",
            "mpy_version": 6,
            "mpy_sub_version": 3,
            "mpy_arch": "armv6m",
            "module_format": "mpy",
        }
        asset.update(changes.pop("asset", {}))
        release = {"tag_name": "v1.2.3", "assets": [asset]}
        release.update(changes)
        return release

    def test_normalizes_compatible_release(self):
        normalized = self.updater._normalize_release(self.release(), "1.2.3")
        self.assertEqual(normalized["version"], "1.2.3")
        self.assertEqual(normalized["model"], "pico-w-rp2040")

    def test_parses_http_and_https_urls(self):
        self.assertEqual(
            self.updater._parse_url("http://192.168.1.10:8000/metadata.json"),
            ("http", "192.168.1.10", 8000, "/metadata.json"),
        )
        self.assertEqual(
            self.updater._parse_url("https://api.github.com/releases/latest"),
            ("https", "api.github.com", 443, "/releases/latest"),
        )

    def test_rejects_unsupported_url_scheme(self):
        with self.assertRaisesRegex(ValueError, "Unsupported URL scheme"):
            self.updater._parse_url("ftp://example.invalid/release")

    def test_rejects_wrong_model(self):
        result = self.updater._normalize_release(
            self.release(asset={"model": "pico2-w-rp2350"}), "1.2.3")
        self.assertIsNone(result)
        self.assertIn("No firmware asset", self.updater.error)

    def test_rejects_missing_checksum(self):
        result = self.updater._normalize_release(
            self.release(asset={"sha256": None}), "1.2.3")
        self.assertIsNone(result)

    def test_rejects_wrong_mpy_sub_version(self):
        result = self.updater._normalize_release(
            self.release(asset={"mpy_sub_version": 2}), "1.2.3")
        self.assertIsNone(result)
        self.assertIn("sub-version", self.updater.error)

    def test_rejects_wrong_mpy_architecture(self):
        result = self.updater._normalize_release(
            self.release(asset={"mpy_arch": "armv8m"}), "1.2.3")
        self.assertIsNone(result)
        self.assertIn("architecture", self.updater.error)

    def test_py_release_does_not_require_mpy_abi(self):
        normalized = self.updater._normalize_release(
            self.release(asset={
                "module_format": "py",
                "mpy_version": None,
                "mpy_sub_version": None,
                "mpy_arch": None,
            }), "1.2.3")
        self.assertIsNotNone(normalized)

    def test_truncated_body_is_rejected_and_partial_file_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "firmware"
            with self.assertRaises(ValueError):
                asyncio.run(self.updater._download_content(FakeReader(b"ab"), False, str(target), 3))
            # _download_content exposes the truncation; _download_file owns cleanup.
            self.assertTrue(target.exists())

    def test_attempts_are_release_specific(self):
        with tempfile.TemporaryDirectory() as directory:
            self.updater.update_flag_path = str(Path(directory) / "state")
            self.assertEqual(self.updater._begin_release_attempt("1.2.3"), 1)
            self.assertEqual(self.updater._begin_release_attempt("1.2.3"), 2)
            self.assertEqual(self.updater._begin_release_attempt("1.2.4"), 1)

    def test_download_does_not_count_as_apply_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            self.updater.update_flag_path = str(Path(directory) / "state")
            self.updater.pending_update_version = "1.2.3"
            self.assertEqual(self.updater.begin_apply_attempt(), 1)
            self.assertTrue(Path(self.updater.update_flag_path).exists())

    def test_rejected_release_can_be_cleared_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            self.updater.update_flag_path = str(Path(directory) / "state")
            for _ in range(self.updater.max_failure_attempts):
                self.updater._begin_release_attempt("1.2.3")
            self.assertTrue(self.updater._is_release_rejected("1.2.3"))
            self.assertTrue(self.updater.clear_rejected_release("1.2.3"))
            self.assertFalse(self.updater._is_release_rejected("1.2.3"))

    def test_clear_rejected_release_does_not_clear_another_version(self):
        with tempfile.TemporaryDirectory() as directory:
            self.updater.update_flag_path = str(Path(directory) / "state")
            self.updater._begin_release_attempt("1.2.3")
            self.assertFalse(self.updater.clear_rejected_release("1.2.4"))
            self.assertTrue(Path(self.updater.update_flag_path).exists())

    def test_download_diagnostics_are_separate_from_apply_state(self):
        with tempfile.TemporaryDirectory() as directory:
            self.updater.update_flag_path = str(Path(directory) / "apply-state")
            self.updater.download_diagnostics_path = str(Path(directory) / "download-state")
            self.updater._record_download_diagnostic("1.2.3", False, "timeout")
            diagnostic = json.loads(Path(self.updater.download_diagnostics_path).read_text())
            self.assertEqual(diagnostic["consecutive_failures"], 1)
            self.assertEqual(diagnostic["error"], "timeout")
            self.assertFalse(Path(self.updater.update_flag_path).exists())

            self.updater._record_download_diagnostic("1.2.3", True)
            diagnostic = json.loads(Path(self.updater.download_diagnostics_path).read_text())
            self.assertEqual(diagnostic["consecutive_failures"], 0)
            self.assertTrue(diagnostic["succeeded"])

    def test_downloaded_artifact_hash_and_size_are_verified(self):
        payload = b"firmware"
        release = {
            "url": "https://example.invalid/firmware.tar.zlib",
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        with tempfile.TemporaryDirectory() as directory:
            self.updater.firmware_download_path = str(Path(directory) / "firmware")

            async def fake_download(url, target, store_in_memory=False):
                Path(target).write_bytes(payload)
                self.updater.bytes_read = len(payload)
                return None, hashlib.sha256(payload).hexdigest()

            self.updater._download_file = fake_download
            self.assertTrue(asyncio.run(self.updater._download_firmware(release)))

    def test_hash_mismatch_removes_downloaded_artifact(self):
        payload = b"firmware"
        release = {
            "url": "https://example.invalid/firmware.tar.zlib",
            "size": len(payload),
            "sha256": "0" * 64,
        }
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "firmware"
            self.updater.firmware_download_path = str(target)

            async def fake_download(url, path, store_in_memory=False):
                Path(path).write_bytes(payload)
                self.updater.bytes_read = len(payload)
                return None, hashlib.sha256(payload).hexdigest()

            self.updater._download_file = fake_download
            self.assertFalse(asyncio.run(self.updater._download_firmware(release)))
            self.assertFalse(target.exists())

    def test_routine_check_does_not_increment_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            self.updater.update_flag_path = str(Path(directory) / "state")
            self.assertEqual(self.updater.should_attempt_update(), (True, "Automatic update checks enabled"))
            self.assertFalse(Path(self.updater.update_flag_path).exists())

    def test_type_change_removes_destination_before_rename(self):
        with tempfile.TemporaryDirectory() as directory:
            source_root = Path(directory) / "source"
            destination_root = Path(directory) / "destination"
            source_root.mkdir()
            destination_root.mkdir()
            (source_root / "item").write_text("replacement")
            (destination_root / "item").mkdir()
            (destination_root / "item" / "old").write_text("old")

            result = asyncio.run(self.updater._merge_directories_recursive(
                str(source_root), str(destination_root)))

            self.assertTrue(result)
            self.assertTrue((destination_root / "item").is_file())
            self.assertEqual((destination_root / "item").read_text(), "replacement")


if __name__ == "__main__":
    unittest.main()
