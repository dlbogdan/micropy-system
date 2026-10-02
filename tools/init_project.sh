#!/bin/sh
set -eu

usage() {
    cat <<'EOF'
Usage: init_project.sh [PROJECT_ROOT]

Initialize an application repository that contains micropy-system at
vendor/micropy-system. Existing files are never overwritten.
EOF
}

case "${1:-}" in
    -h|--help)
        usage
        exit 0
        ;;
esac

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
FRAMEWORK_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

if [ "$#" -gt 1 ]; then
    usage >&2
    exit 2
fi

if [ "$#" -eq 1 ]; then
    PROJECT_ROOT=$(CDPATH= cd -- "$1" && pwd)
else
    PROJECT_ROOT=$(git -C "$FRAMEWORK_ROOT" rev-parse --show-superproject-working-tree 2>/dev/null || true)
    if [ -z "$PROJECT_ROOT" ]; then
        echo "Error: PROJECT_ROOT is required when micropy-system is not a submodule." >&2
        exit 2
    fi
fi

SUBMODULE_PATH=""
if [ -f "$PROJECT_ROOT/.gitmodules" ]; then
    for candidate in $(git -C "$PROJECT_ROOT" config --file .gitmodules --get-regexp path 2>/dev/null | awk '{print $2}'); do
        candidate_root=$(CDPATH= cd -- "$PROJECT_ROOT/$candidate" 2>/dev/null && pwd -P || true)
        framework_physical=$(CDPATH= cd -- "$FRAMEWORK_ROOT" && pwd -P)
        if [ "$candidate_root" = "$framework_physical" ]; then
            SUBMODULE_PATH=$candidate
            break
        fi
    done
fi
if [ -z "$SUBMODULE_PATH" ]; then
    echo "Error: could not identify this framework in PROJECT_ROOT/.gitmodules." >&2
    exit 2
fi

write_file() {
    relative_path=$1
    target="$PROJECT_ROOT/$relative_path"
    if [ -e "$target" ]; then
        echo "Keeping existing $relative_path"
        cat >/dev/null
        return
    fi
    mkdir -p "$(dirname -- "$target")"
    cat >"$target"
    echo "Created $relative_path"
}

append_ignore() {
    entry=$1
    ignore_file="$PROJECT_ROOT/.gitignore"
    touch "$ignore_file"
    if ! grep -Fqx "$entry" "$ignore_file"; then
        printf '%s\n' "$entry" >>"$ignore_file"
    fi
}

# Create the minimal MicroPico workspace setting once. write_file() is
# idempotent and preserves an existing user-managed settings file unchanged.
write_file .vscode/settings.json <<'EOF'
{
    "micropico.syncFolder": "device"
}
EOF

write_file tools/update_framework.sh <<EOF
#!/bin/sh
set -eu
APP_ROOT=\$(CDPATH= cd -- "\$(dirname -- "\$0")/.." && pwd)
SUBMODULE="$SUBMODULE_PATH"
git -C "\$APP_ROOT" submodule update --init "\$SUBMODULE"
git -C "\$APP_ROOT/\$SUBMODULE" fetch origin main
git -C "\$APP_ROOT/\$SUBMODULE" checkout main
git -C "\$APP_ROOT/\$SUBMODULE" merge --ff-only origin/main
echo "Framework updated. Review and commit the submodule pointer:"
echo "  git add \$SUBMODULE && git commit -m 'Update micropy-system framework'"
EOF

write_file tools/assemble.py <<EOF
#!/usr/bin/env python3
"""Shim: the canonical assembler lives in the micropy-system framework ($SUBMODULE_PATH/tools/assemble.py)."""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["MICROPY_APP_ROOT"] = ROOT
os.execv(sys.executable, [sys.executable,
    os.path.join(ROOT, "$SUBMODULE_PATH", "tools", "assemble.py"),
    "--app-root", ROOT] + sys.argv[1:])
EOF

write_file tools/device.py <<EOF
#!/usr/bin/env python3
"""Shim: the canonical USB device CLI lives in the micropy-system framework ($SUBMODULE_PATH/tools/device.py)."""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["MICROPY_APP_ROOT"] = ROOT
os.execv(sys.executable, [sys.executable,
    os.path.join(ROOT, "$SUBMODULE_PATH", "tools", "device.py")] + sys.argv[1:])
EOF

write_file tools/console.py <<EOF
#!/usr/bin/env python3
"""Shim: the canonical network REPL client lives in the micropy-system framework ($SUBMODULE_PATH/tools/console.py)."""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["MICROPY_APP_ROOT"] = ROOT
os.execv(sys.executable, [sys.executable,
    os.path.join(ROOT, "$SUBMODULE_PATH", "tools", "console.py")] + sys.argv[1:])
EOF

write_file tools/discover.py <<EOF
#!/usr/bin/env python3
"""Shim: the canonical LAN scanner lives in the micropy-system framework ($SUBMODULE_PATH/tools/discover.py)."""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["MICROPY_APP_ROOT"] = ROOT
os.execv(sys.executable, [sys.executable,
    os.path.join(ROOT, "$SUBMODULE_PATH", "tools", "discover.py")] + sys.argv[1:])
EOF

write_file tools/provision.sh <<EOF
#!/bin/sh
# Shim: the canonical provisioning engine lives in the micropy-system framework.
set -eu
APP_ROOT=\$(CDPATH= cd -- "\$(dirname -- "\$0")/.." && pwd)
exec "\$APP_ROOT/$SUBMODULE_PATH/tools/provision.sh" \
    --app-root "\$APP_ROOT" --boot-marker "entering main loop" "\$@"
EOF

write_file tools/setup_build_env.sh <<EOF
#!/bin/sh
# Shim: canonical venv setup lives in the framework ($SUBMODULE_PATH/tools/setup_build_env.sh).
set -eu
APP_ROOT=\$(CDPATH= cd -- "\$(dirname -- "\$0")/.." && pwd)
exec "\$APP_ROOT/$SUBMODULE_PATH/tools/setup_build_env.sh" --app-root "\$APP_ROOT" "\$@"
EOF

write_file tools/build_firmware.sh <<EOF
#!/bin/sh
# Shim: canonical builder lives in the framework ($SUBMODULE_PATH/tools/build_firmware.sh).
set -eu
APP_ROOT=\$(CDPATH= cd -- "\$(dirname -- "\$0")/.." && pwd)
exec "\$APP_ROOT/$SUBMODULE_PATH/tools/build_firmware.sh" --app-root "\$APP_ROOT" "\$@"
EOF

write_file tools/serve_update.sh <<EOF
#!/bin/sh
# Shim: canonical OTA update server lives in the framework ($SUBMODULE_PATH/tools/serve_update.sh).
set -eu
APP_ROOT=\$(CDPATH= cd -- "\$(dirname -- "\$0")/.." && pwd)
exec "\$APP_ROOT/$SUBMODULE_PATH/tools/serve_update.sh" --app-root "\$APP_ROOT" "\$@"
EOF

write_file tools/release_github.sh <<EOF
#!/bin/sh
# Shim: canonical GitHub release cutter lives in the framework ($SUBMODULE_PATH/tools/release_github.sh).
set -eu
APP_ROOT=\$(CDPATH= cd -- "\$(dirname -- "\$0")/.." && pwd)
exec "\$APP_ROOT/$SUBMODULE_PATH/tools/release_github.sh" --app-root "\$APP_ROOT" "\$@"
EOF

write_file tools/net.sh <<EOF
#!/bin/sh
# Shim: canonical device API client lives in the framework ($SUBMODULE_PATH/tools/net.sh).
set -eu
APP_ROOT=\$(CDPATH= cd -- "\$(dirname -- "\$0")/.." && pwd)
exec "\$APP_ROOT/$SUBMODULE_PATH/tools/net.sh" --app-root "\$APP_ROOT" "\$@"
EOF

write_file tools/deploy.sh <<EOF
#!/bin/sh
# Shim: canonical deploy orchestrator lives in the framework ($SUBMODULE_PATH/tools/deploy.sh).
set -eu
APP_ROOT=\$(CDPATH= cd -- "\$(dirname -- "\$0")/.." && pwd)
exec "\$APP_ROOT/$SUBMODULE_PATH/tools/deploy.sh" --app-root "\$APP_ROOT" "\$@"
EOF

write_file tools/device.sh <<EOF
#!/bin/sh
# Shim: run the canonical USB device CLI with the project's venv Python.
set -eu
APP_ROOT=\$(CDPATH= cd -- "\$(dirname -- "\$0")/.." && pwd)
PY="\$APP_ROOT/.venv/bin/python"
[ -x "\$PY" ] || PY=python3
exec env MICROPY_APP_ROOT="\$APP_ROOT" "\$PY" "\$APP_ROOT/$SUBMODULE_PATH/tools/device.py" "\$@"
EOF

write_file app/main.py <<'EOF'
import uasyncio as asyncio
from machine import Pin
import lib.coresys.logger as logger

MESSAGE = "Hello world from micropy-system-test!"


async def main():
    # Framework provisioning convention: this line is the default
    # --boot-marker the provisioning engine waits for over serial.
    logger.info("entering main loop", log_to_file=True)
    led = Pin("LED", Pin.OUT)
    print(MESSAGE)
    while True:
        led.toggle()
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
EOF

write_file app/version.txt <<'EOF'
1.0.0
EOF

write_file system-config.example.json <<'EOF'
{
  "DEVICE": {
    "NAME": "micropy-system-test",
    "MODEL": "pico2-w-rp2350"
  },
  "WIFI": {
    "SSID": "your-wifi-ssid",
    "PASS": "your-wifi-password"
  },
  "FIRMWARE": {
    "GITHUB_REPO": "owner/application-repository",
    "GITHUB_TOKEN": "",
    "DIRECT_BASE_URL": null,
    "UPDATE_ON_BOOT": true,
    "CHUNK_SIZE": 2048,
    "MAX_REDIRECTS": 10,
    "CORE_SYSTEM_FILES": [
      "boot.py",
      "main.py",
      "lib/coresys/manager_firmware.mpy",
      "lib/coresys/manager_system.mpy",
      "lib/coresys/manager_wifi.mpy",
      "lib/coresys/manager_config.mpy",
      "lib/coresys/logger.mpy",
      "lib/coresys/manager_tasks.mpy"
    ],
    "MAX_FAILURE_ATTEMPTS": 3,
    "NETWORK_TIMEOUT_MS": 60000,
    "REQUEST_TIMEOUT_MS": 15000,
    "RUNTIME_VERSION": "1.29.0",
    "MPY_VERSION": 6,
    "MPY_SUB_VERSION": 3,
    "MPY_ARCH": "armv8m"
  }
}
EOF

write_file .github/workflows/release-firmware.yml <<EOF
name: Build firmware release

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
          cache-dependency-path: "$SUBMODULE_PATH/requirements.txt"
      - name: Install build toolchain
        run: python -m pip install --requirement "$SUBMODULE_PATH/requirements.txt"
      - name: Resolve version
        id: version
        shell: bash
        env:
          MANUAL_VERSION: \${{ inputs.version }}
        run: |
          if [[ "\${GITHUB_REF_TYPE}" == "tag" ]]; then
            VERSION="\${GITHUB_REF_NAME#v}"
            TAG="\${GITHUB_REF_NAME}"
          else
            VERSION="\${MANUAL_VERSION#v}"
            TAG="v\${VERSION}"
          fi
          [[ "\${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 2
          echo "version=\${VERSION}" >> "\${GITHUB_OUTPUT}"
          echo "tag=\${TAG}" >> "\${GITHUB_OUTPUT}"
      - name: Assemble device tree
        run: python tools/assemble.py
      - name: Build firmware
        run: >-
          python "$SUBMODULE_PATH/local_builder.py"
          --source-dir device
          --output-dir build
          --model pico2-w-rp2350
          --version "\${{ steps.version.outputs.version }}"
      - name: Publish release
        env:
          GH_TOKEN: \${{ github.token }}
        run: |
          gh release create "\${{ steps.version.outputs.tag }}" \\
            build/pico2-w-rp2350-firmware.tar.zlib \\
            --repo "\${GITHUB_REPOSITORY}" \\
            --target "\${GITHUB_SHA}" \\
            --title "Firmware \${{ steps.version.outputs.tag }}" \\
            --generate-notes
EOF

write_file README.md <<'EOF'
# MicroPython application

This application uses `micropy-system` as a pinned Git submodule.

## Common commands

```sh
# One-time local toolchain setup
tools/setup_build_env.sh

# Assemble and build app/version.txt for Pico 2 W
tools/build_firmware.sh

# Build an explicit version/model locally
tools/build_firmware.sh 1.0.1 pico2-w-rp2350

# Serve build/ over local HTTP, then use the printed OTA URL as DIRECT_BASE_URL
tools/serve_update.sh

# Update the framework checkout; review and commit its pointer afterward
tools/update_framework.sh

# Trigger the GitHub release workflow by pushing a clean annotated tag
tools/release_github.sh 1.0.1
```

For a manual GitHub run, open **Actions → Build firmware release → Run
workflow** and enter a semantic version. The release workflow also runs when a
`vMAJOR.MINOR.PATCH` tag is pushed.

For MicroPico deployment, copy `system-config.example.json` to the ignored
`system-config.json`, edit it, run `python3 tools/assemble.py`, and configure
MicroPico's sync folder as `device`.

The initializer creates a minimal `.vscode/settings.json` with MicroPico's sync
folder set to `device`. This is idempotent: an existing settings file is kept
unchanged. Do not use the repository root as the sync folder because it would
copy host-only `vendor`, `tools`, `build`, and nested `device` trees to flash.

The first transition from an HTTPS-only framework build to local HTTP must be
provisioned once through USB/MicroPico because the installed old updater cannot
download HTTP. After synchronization, ensure no stale
`lib/coresys/manager_firmware.mpy` remains beside the assembled `.py`, reset the
board, and then use local HTTP OTA normally.
EOF

for entry in '.vscode/' '.micropico' '.venv/' '__pycache__/' '*.pyc' 'device/' 'build/' 'release/' 'system-config.json'; do
    append_ignore "$entry"
done

chmod +x \
    "$PROJECT_ROOT/tools/update_framework.sh" \
    "$PROJECT_ROOT/tools/assemble.py" \
    "$PROJECT_ROOT/tools/setup_build_env.sh" \
    "$PROJECT_ROOT/tools/build_firmware.sh" \
    "$PROJECT_ROOT/tools/serve_update.sh" \
    "$PROJECT_ROOT/tools/release_github.sh" \
    "$PROJECT_ROOT/tools/device.py" \
    "$PROJECT_ROOT/tools/console.py" \
    "$PROJECT_ROOT/tools/discover.py" \
    "$PROJECT_ROOT/tools/provision.sh" \
    "$PROJECT_ROOT/tools/net.sh" \
    "$PROJECT_ROOT/tools/deploy.sh" \
    "$PROJECT_ROOT/tools/device.sh"

echo
echo "Project initialized at $PROJECT_ROOT"
echo "Next: copy system-config.example.json to system-config.json, edit it,"
echo "then run: python3 tools/assemble.py"
