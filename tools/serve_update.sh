#!/bin/sh
# Compatibility entry point; the OTA server launcher is implemented in Python.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$SCRIPT_DIR/serve_update.py" "$@"
