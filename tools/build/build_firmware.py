#!/usr/bin/env python3
"""Assemble and build a micropy-system application firmware package."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tooling import framework_root, project_python, resolve_app_root


SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", nargs="?")
    parser.add_argument("model", nargs="?", default="pico2-w-rp2350")
    parser.add_argument("--app-root")
    parser.add_argument("--source-dir", default="app")
    parser.add_argument("--output-dir", default="build")
    return parser.parse_args(argv)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    args = parse_args(argv)
    root = framework_root()
    app_root = resolve_app_root(args.app_root)
    try:
        python = project_python(app_root)
    except FileNotFoundError as error:
        raise SystemExit("Error: %s" % error)
    version = args.version or (app_root / "app" / "version.txt").read_text().strip()
    if not SEMVER.fullmatch(version):
        raise SystemExit("Error: version must have the form MAJOR.MINOR.PATCH")

    print("==> Assembling device tree")
    subprocess.run(
        [str(python), str(root / "tools" / "build" / "assemble.py"),
         "--app-root", str(app_root)], check=True)
    print("==> Building firmware %s for %s" % (version, args.model))
    environment = os.environ.copy()
    environment["PATH"] = str(python.parent) + os.pathsep + environment.get("PATH", "")
    subprocess.run(
        [str(python), str(root / "local_builder.py"),
         "--source-dir", str(app_root / args.source_dir),
         "--output-dir", str(app_root / args.output_dir),
         "--model", args.model, "--version", version],
        check=True, env=environment)
    print("==> Build complete: %s" % (app_root / args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
