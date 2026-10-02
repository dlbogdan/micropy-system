#!/bin/sh
# Compatibility entry point; project initialization is implemented in Python.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$SCRIPT_DIR/init_project.py" "$@"
