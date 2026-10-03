#!/usr/bin/env python3
"""Select the Pico W or Pico 2 W IntelliSense stub profile."""

import argparse
from pathlib import Path
import shutil
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"
STUB_ROOT = PROJECT_ROOT / ".stubs"
ACTIVE_LINK = PROJECT_ROOT / ".micropython-stubs"
PROFILES = {
    "pico-w": {
        "directory": STUB_ROOT / "pico-w-1.29",
        "requirements": PROJECT_ROOT / "requirements-stubs-pico-w.txt",
    },
    "pico2-w": {
        "directory": STUB_ROOT / "pico2-w-1.29",
        "requirements": PROJECT_ROOT / "requirements-stubs-pico2-w.txt",
    },
}


def install_profile(profile):
    target = profile["directory"]
    target.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(PYTHON),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--target",
            str(target),
            "-r",
            str(profile["requirements"]),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )


def replace_active_link(target):
    if ACTIVE_LINK.is_symlink() or ACTIVE_LINK.is_file():
        ACTIVE_LINK.unlink()
    elif ACTIVE_LINK.is_dir():
        shutil.rmtree(ACTIVE_LINK)
    ACTIVE_LINK.symlink_to(target.relative_to(PROJECT_ROOT), target_is_directory=True)


def main():
    parser = argparse.ArgumentParser(
        description="Install and select MicroPython 1.29 editor stubs"
    )
    parser.add_argument("profile", choices=sorted(PROFILES))
    parser.add_argument(
        "--no-install",
        action="store_true",
        help="select an already installed profile without running pip",
    )
    args = parser.parse_args()

    if not PYTHON.exists():
        print("Missing .venv; create it from requirements-dev.txt first", file=sys.stderr)
        return 2

    profile = PROFILES[args.profile]
    if not args.no_install:
        install_profile(profile)
    elif not profile["directory"].exists():
        print("Stub profile is not installed: {}".format(profile["directory"]), file=sys.stderr)
        return 2

    replace_active_link(profile["directory"])
    print("Selected MicroPython 1.29 stubs for {}".format(args.profile))
    print("Reload the VS Code window if IntelliSense does not refresh automatically.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
