import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

import local_builder


class BuildVersionTests(unittest.TestCase):
    def test_writes_version_without_release_tag_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            path = local_builder.write_build_version(directory, "v1.2.3-4-gabc123")
            self.assertEqual(Path(path).read_text(), "1.2.3-4-gabc123\n")

    def test_generated_version_is_hashed_and_packaged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            temporary = root / "temporary"
            source.mkdir()
            temporary.mkdir()
            local_builder.write_build_version(str(temporary), "v1.2.3")
            archive = root / "release.tar"

            local_builder.create_tar_archive(str(source), str(archive), str(temporary))

            with tarfile.open(archive) as release:
                self.assertIn("version.txt", release.getnames())
                integrity = json.load(io.TextIOWrapper(release.extractfile("integrity.json")))
                self.assertIn("version.txt", integrity)
                self.assertEqual(release.extractfile("version.txt").read(), b"1.2.3\n")


if __name__ == "__main__":
    unittest.main()
