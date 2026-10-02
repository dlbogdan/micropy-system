#!/bin/sh
# Compatibility entry point; release tagging is implemented in Python.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$SCRIPT_DIR/release_github.py" "$@"
