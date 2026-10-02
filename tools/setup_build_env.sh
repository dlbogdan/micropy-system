#!/bin/sh
# Compatibility entry point; environment setup is implemented in Python.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$SCRIPT_DIR/setup_build_env.py" "$@"
