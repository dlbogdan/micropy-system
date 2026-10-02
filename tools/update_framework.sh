#!/bin/sh
# Compatibility entry point; framework updates are implemented in Python.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$SCRIPT_DIR/update_framework.py" "$@"
