import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

import local_builder


class BuildVersionTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
