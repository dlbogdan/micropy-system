#!/bin/sh
# Compatibility entry point; firmware builds are implemented in Python.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$SCRIPT_DIR/build_firmware.py" "$@"
