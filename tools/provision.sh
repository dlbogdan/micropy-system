#!/bin/sh
# Compatibility entry point; provisioning is implemented portably in Python.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$SCRIPT_DIR/provision.py" "$@"
