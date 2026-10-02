#!/bin/sh
# Compatibility entry point; network commands are implemented in Python.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$SCRIPT_DIR/net.py" "$@"
