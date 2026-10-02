#!/usr/bin/env python3
"""Initialize a consuming micropy-system project without overwriting files."""

import argparse
import json
from pathlib import Path
import subprocess

from tooling import framework_root


APP_MAIN = '''import uasyncio as asyncio
from machine import Pin
import lib.coresys.logger as logger

MESSAGE = "Hello world from micropy-system-test!"


async def main():
    logger.info("entering main loop", log_to_file=True)
    led = Pin("LED", Pin.OUT)
    print(MESSAGE)
    while True:
        led.toggle()
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
'''

SYSTEM_CONFIG = {
    "DEVICE": {"NAME": "micropy-system-test", "MODEL": "pico2-w-rp2350"},
    "WIFI": {"SSID": "your-wifi-ssid", "PASS": "your-wifi-password"},
    "FIRMWARE": {
        "GITHUB_REPO": "owner/application-repository", "GITHUB_TOKEN": "",
        "DIRECT_BASE_URL": None, "UPDATE_ON_BOOT": True, "CHUNK_SIZE": 2048,
        "MAX_REDIRECTS": 10,
        "CORE_SYSTEM_FILES": [
            "boot.py", "main.py", "lib/coresys/manager_firmware.mpy",
            "lib/coresys/manager_system.mpy", "lib/coresys/manager_wifi.mpy",
            "lib/coresys/manager_config.mpy", "lib/coresys/logger.mpy",
            "lib/coresys/manager_tasks.mpy"],
        "MAX_FAILURE_ATTEMPTS": 3, "NETWORK_TIMEOUT_MS": 60000,
        "REQUEST_TIMEOUT_MS": 15000, "RUNTIME_VERSION": "1.29.0",
        "MPY_VERSION": 6, "MPY_SUB_VERSION": 3, "MPY_ARCH": "armv8m",
    },
}

WORKFLOW = '''name: Build firmware release

on:
  push:
    tags:
      - "v*.*.*"
  workflow_dispatch:
    inputs:
      version:
        description: "Semantic version without the v prefix"
        required: true

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: recursive
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: "__SUBMODULE__/requirements.txt"
      - name: Install build toolchain
        run: python -m pip install --requirement "__SUBMODULE__/requirements.txt"
      - name: Resolve version
        id: version
        shell: bash
        env:
          MANUAL_VERSION: ${{ inputs.version }}
        run: |
          if [[ "${GITHUB_REF_TYPE}" == "tag" ]]; then
            VERSION="${GITHUB_REF_NAME#v}"
            TAG="${GITHUB_REF_NAME}"
          else
            VERSION="${MANUAL_VERSION#v}"
            TAG="v${VERSION}"
          fi
          [[ "${VERSION}" =~ ^[0-9]+\\.[0-9]+\\.[0-9]+$ ]] || exit 2
          echo "version=${VERSION}" >> "${GITHUB_OUTPUT}"
          echo "tag=${TAG}" >> "${GITHUB_OUTPUT}"
      - name: Assemble device tree
        run: python "__SUBMODULE__/tools/assemble.py"
      - name: Build firmware
        run: >-
          python "__SUBMODULE__/local_builder.py"
          --source-dir device
          --output-dir build
          --model pico2-w-rp2350
          --version "${{ steps.version.outputs.version }}"
      - name: Publish release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh release create "${{ steps.version.outputs.tag }}" \\
            build/pico2-w-rp2350-firmware.tar.zlib \\
            --repo "${GITHUB_REPOSITORY}" \\
            --target "${GITHUB_SHA}" \\
            --title "Firmware ${{ steps.version.outputs.tag }}" \\
            --generate-notes
'''

README = '''# MicroPython application

This application uses `micropy-system` as a pinned Git submodule.

## Common commands

```sh
# One-time local toolchain setup
__SUBMODULE__/tools/setup_build_env.sh

# Build, serve, deploy, and maintain
__SUBMODULE__/tools/build_firmware.sh
__SUBMODULE__/tools/serve_update.sh
__SUBMODULE__/tools/deploy.sh
__SUBMODULE__/tools/update_framework.sh

# Trigger the GitHub release workflow
__SUBMODULE__/tools/release_github.sh 1.0.1
```

For MicroPico deployment, copy `system-config.example.json` to the ignored
`system-config.json`, edit it, run `python3 __SUBMODULE__/tools/assemble.py`,
and configure MicroPico's sync folder as `device`.

The initializer creates a minimal `.vscode/settings.json` and preserves any
existing user-managed file. Never use the repository root as the sync folder.
'''

IGNORE_ENTRIES = (
    ".vscode/", ".micropico", ".venv/", "__pycache__/", "*.pyc", "device/",
    "build/", "release/", "system-config.json", ".micropy-device-ip",
)


def git_output(*arguments, cwd):
    return subprocess.run(
        ["git", *arguments], cwd=cwd, capture_output=True, text=True,
        check=False).stdout.strip()


def identify_submodule(project):
    modules = project / ".gitmodules"
    if not modules.is_file():
        return None
    output = git_output("config", "--file", ".gitmodules", "--get-regexp",
                        "path", cwd=project)
    actual = framework_root().resolve()
    for line in output.splitlines():
        fields = line.split(None, 1)
        if len(fields) == 2:
            candidate = fields[1]
            path = project / candidate
            if path.exists() and path.resolve() == actual:
                return candidate
    return None


def write_new(project, relative, content):
    target = project / relative
    if target.exists():
        print("Keeping existing %s" % relative)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    print("Created %s" % relative)


def initialize(project):
    submodule = identify_submodule(project)
    if not submodule:
        raise RuntimeError(
            "could not identify this framework in PROJECT_ROOT/.gitmodules")
    write_new(project, ".vscode/settings.json",
              json.dumps({"micropico.syncFolder": "device"}, indent=4) + "\n")
    write_new(project, "app/main.py", APP_MAIN)
    write_new(project, "app/version.txt", "1.0.0\n")
    write_new(project, "system-config.example.json",
              json.dumps(SYSTEM_CONFIG, indent=2) + "\n")
    write_new(project, ".github/workflows/release-firmware.yml",
              WORKFLOW.replace("__SUBMODULE__", submodule))
    write_new(project, "README.md", README.replace("__SUBMODULE__", submodule))

    ignore = project / ".gitignore"
    existing = ignore.read_text().splitlines() if ignore.is_file() else []
    additions = [entry for entry in IGNORE_ENTRIES if entry not in existing]
    if additions:
        with ignore.open("a") as output:
            if existing and ignore.stat().st_size and not ignore.read_text().endswith("\n"):
                output.write("\n")
            output.write("\n".join(additions) + "\n")

    print("\nProject initialized at %s" % project)
    print("Next: configure system-config.json, then run:")
    print("  python3 %s/tools/assemble.py" % submodule)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", nargs="?")
    args = parser.parse_args(argv)
    if args.project_root:
        project = Path(args.project_root).resolve()
    else:
        parent = git_output("-C", str(framework_root()), "rev-parse",
                            "--show-superproject-working-tree", cwd=Path.cwd())
        if not parent:
            raise SystemExit(
                "Error: PROJECT_ROOT is required outside a Git submodule")
        project = Path(parent).resolve()
    try:
        initialize(project)
    except RuntimeError as error:
        raise SystemExit("Error: %s" % error)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
