import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
INITIALIZER = FRAMEWORK_ROOT / "tools" / "init_project.sh"
ASSEMBLER = FRAMEWORK_ROOT / "tools" / "assemble.py"


class InitProjectIntegrationTests(unittest.TestCase):
    def test_initialized_project_assembles_with_framework_owned_tooling(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            submodule = project / "vendor" / "micropy-system"
            submodule.parent.mkdir(parents=True)
            submodule.symlink_to(FRAMEWORK_ROOT, target_is_directory=True)
            (project / ".gitmodules").write_text(
                '[submodule "vendor/micropy-system"]\n'
                "\tpath = vendor/micropy-system\n"
                "\turl = https://example.invalid/micropy-system.git\n",
                encoding="utf-8",
            )

            subprocess.run(
                [str(INITIALIZER), str(project)],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertFalse((project / "tools").exists())
            self.assertIn(
                'run: python "vendor/micropy-system/tools/assemble.py"',
                (project / ".github" / "workflows" / "release-firmware.yml").read_text(),
            )
            self.assertIn(
                ".micropy-device-ip",
                (project / ".gitignore").read_text().splitlines(),
            )

            subprocess.run(
                [sys.executable, str(ASSEMBLER), "--app-root", str(project)],
                check=True,
                capture_output=True,
                text=True,
            )

            device = project / "device"
            self.assertTrue((device / ".micropy-system-device-tree").is_file())
            self.assertTrue((device / "main.py").is_file())
            self.assertTrue((device / "apps" / "a" / "app_entry.py").is_file())


if __name__ == "__main__":
    unittest.main()
