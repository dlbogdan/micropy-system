import io
import json
from pathlib import Path
import socket
import tarfile
import tempfile
import unittest
import zlib

import local_builder
import prepare_release
import firmware_server


class BuildVersionTests(unittest.TestCase):
    def test_initializer_writes_only_the_idempotent_sync_folder_setting(self):
        initializer = (Path(__file__).parents[1] / 'tools' / 'init_project.sh').read_text()
        self.assertIn('write_file .vscode/settings.json', initializer)
        self.assertIn('"micropico.syncFolder": "device"', initializer)
        self.assertNotIn('"micropico.openOnStart"', initializer)
        self.assertNotIn('"micropico.autoConnect"', initializer)
        self.assertNotIn('write_file .micropico', initializer)
        self.assertIn('.micropy-system-device-tree', initializer)

    def test_legacy_packager_defaults_to_canonical_github_adapter(self):
        args = prepare_release.compatibility_args([])
        self.assertIn('github-assets', args)
        self.assertIn('release', args)
        self.assertIn('pico-w-rp2040', args)

    def test_writes_framework_git_build_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            path = local_builder.write_framework_build(
                directory,
                "v1.2.3-4-gabc123-dirty",
                "2026-09-14T08:00:00Z",
            )
            self.assertEqual(Path(path).name, "framework-build.txt")
            self.assertEqual(
                Path(path).read_text(),
                "v1.2.3-4-gabc123-dirty built 2026-09-14T08:00:00Z\n",
            )

    def test_framework_build_is_hashed_and_packaged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            temporary = root / "temporary"
            source.mkdir()
            temporary.mkdir()
            local_builder.write_framework_build(
                str(temporary),
                "v1.2.3-4-gabc123",
                "2026-09-14T08:00:00Z",
            )
            archive = root / "release.tar"

            local_builder.create_tar_archive(str(source), str(archive), str(temporary))

            with tarfile.open(archive) as release:
                self.assertIn("framework-build.txt", release.getnames())
                integrity = json.load(io.TextIOWrapper(release.extractfile("integrity.json")))
                self.assertIn("framework-build.txt", integrity)
                self.assertEqual(
                    release.extractfile("framework-build.txt").read(),
                    b"v1.2.3-4-gabc123 built 2026-09-14T08:00:00Z\n",
                )

    def test_build_date_is_utc(self):
        build_date = local_builder.get_build_date()
        self.assertRegex(build_date, r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')

    def test_github_adapter_writes_sidecar_without_direct_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / 'firmware.tar.zlib'
            artifact.write_bytes(b'archive')
            metadata = local_builder.create_metadata(
                str(artifact), 'v1.2.3', 'owner/repo', 8000,
                'pico-w-rp2040', 'pico-w-rp2040-firmware.tar.zlib',
                directory, 'github-assets')
            self.assertIsNone(metadata)
            sidecar = json.loads((Path(directory) / 'image-info.json').read_text())
            self.assertEqual(sidecar['model'], 'pico-w-rp2040')
            self.assertEqual(sidecar['asset'], 'pico-w-rp2040-firmware.tar.zlib')

    def test_direct_server_adapter_returns_github_shaped_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / 'firmware.tar.zlib'
            artifact.write_bytes(b'archive')
            metadata = local_builder.create_metadata(
                str(artifact), 'v1.2.3', 'owner/repo', 8000,
                'pico-w-rp2040', 'pico-w-rp2040-firmware.tar.zlib',
                directory, 'direct-server')
            self.assertEqual(metadata['tag_name'], 'v1.2.3')
            self.assertEqual(metadata['assets'][0]['model'], 'pico-w-rp2040')
            self.assertTrue(metadata['url'].startswith('http://'))
            self.assertIn(':8000/', metadata['assets'][0]['browser_download_url'])

    def test_stream_compression_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.tar'
            output = Path(directory) / 'firmware.tar.zlib'
            payload = b'abc123' * 50000
            source.write_bytes(payload)
            size = local_builder.compress_zlib(str(source), str(output), chunk_size=127)
            self.assertEqual(size, output.stat().st_size)
            self.assertEqual(zlib.decompress(output.read_bytes()), payload)

    def test_py_module_format_copies_sources_without_mpy_twin(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source'
            prepared = Path(directory) / 'prepared'
            (source / 'lib').mkdir(parents=True)
            prepared.mkdir()
            (source / 'boot.py').write_text('print("boot")')
            (source / 'lib' / 'module.py').write_text('VALUE = 1')
            local_builder.prepare_modules(str(source), str(prepared), 'py')
            self.assertTrue((prepared / 'lib' / 'module.py').is_file())
            self.assertFalse((prepared / 'lib' / 'module.mpy').exists())

    def test_duplicate_py_and_mpy_module_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            prepared = Path(directory)
            (prepared / 'module.py').write_text('VALUE = 1')
            (prepared / 'module.mpy').write_bytes(b'M')
            with self.assertRaisesRegex(ValueError, 'both'):
                local_builder.validate_module_uniqueness(directory)

    def test_server_requires_metadata_and_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'metadata.json'):
                firmware_server.validate_build_directory(directory)
            (Path(directory) / 'metadata.json').write_text('{}')
            (Path(directory) / 'pico-firmware.tar.zlib').write_bytes(b'archive')
            self.assertEqual(
                firmware_server.validate_build_directory(directory),
                ['pico-firmware.tar.zlib'],
            )

    def test_server_reports_an_in_use_port_concisely(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'metadata.json').write_text('{}')
            (Path(directory) / 'pico-firmware.tar.zlib').write_bytes(b'archive')
            occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            occupied.bind(('127.0.0.1', 0))
            occupied.listen(1)
            port = occupied.getsockname()[1]
            try:
                with self.assertRaisesRegex(ValueError, 'already in use'):
                    firmware_server.run_server(directory, '127.0.0.1', port)
            finally:
                occupied.close()


if __name__ == "__main__":
    unittest.main()
