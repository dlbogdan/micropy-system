#!/usr/bin/env python3
"""Create or refresh a project's micropy-system build environment."""

import argparse
from pathlib import Path
import subprocess
import sys

import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tooling import framework_root, resolve_app_root


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root")
    args = parser.parse_args(argv)
    app_root = resolve_app_root(args.app_root)
    venv = app_root / ".venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "pip"],
                   check=True)
    subprocess.run([
        str(python), "-m", "pip", "install", "--requirement",
        str(framework_root() / "requirements-dev.txt")], check=True)
    print("Build environment is ready at %s" % venv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
