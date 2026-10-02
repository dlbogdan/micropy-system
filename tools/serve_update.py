#!/usr/bin/env python3
"""Serve a built firmware package for direct-server OTA."""

import argparse
from pathlib import Path
import subprocess

from tooling import framework_root, project_python, resolve_app_root


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", nargs="?", type=int, default=8000)
    parser.add_argument("--app-root")
    parser.add_argument("--directory")
    args = parser.parse_args(argv)
    app_root = resolve_app_root(args.app_root)
    try:
        python = project_python(app_root)
    except FileNotFoundError as error:
        raise SystemExit("Error: %s" % error)
    directory = Path(args.directory) if args.directory else app_root / "build"
    if not directory.is_absolute():
        directory = app_root / directory
    if not (directory / "metadata.json").is_file():
        raise SystemExit(
            "Error: no direct-server build at %s; build firmware first" % directory)
    return subprocess.call([
        str(python), str(framework_root() / "firmware_server.py"),
        "--directory", str(directory), "--port", str(args.port)])


if __name__ == "__main__":
    raise SystemExit(main())
