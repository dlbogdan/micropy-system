#!/bin/sh
# Create or refresh the project's build venv (canonical: micropy-system).
#
# Installs the framework's requirements-dev.txt (mpy-cross, mpremote,
# pyserial) into <app-root>/.venv. Idempotent: safe to re-run after a
# framework update to pick up new requirements.
#
# Usage: tools/setup_build_env.sh [--app-root PATH]
#
# APP_ROOT resolution: --app-root > $MICROPY_APP_ROOT > git superproject > CWD.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
FRAMEWORK_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

APP_ROOT=""
PENDING=""
for arg in "$@"; do
    if [ -n "$PENDING" ]; then
        APP_ROOT="$arg"
        PENDING=""
        continue
    fi
    case "$arg" in
        --app-root) PENDING=approot ;;
        -h|--help) sed -n '2,/^set -eu$/p' "$0" | sed '$d'; exit 0 ;;
        *) echo "Error: unknown argument '$arg' (try --help)" >&2; exit 2 ;;
    esac
done

if [ -z "$APP_ROOT" ]; then
    APP_ROOT="${MICROPY_APP_ROOT:-}"
fi
if [ -z "$APP_ROOT" ]; then
    APP_ROOT=$(git -C "$FRAMEWORK_ROOT" rev-parse --show-superproject-working-tree 2>/dev/null || true)
fi
if [ -z "$APP_ROOT" ]; then
    APP_ROOT=$(pwd)
fi
APP_ROOT=$(CDPATH= cd -- "$APP_ROOT" && pwd)

python3 -m venv "$APP_ROOT/.venv"
"$APP_ROOT/.venv/bin/python" -m pip install --upgrade pip
"$APP_ROOT/.venv/bin/python" -m pip install \
    --requirement "$FRAMEWORK_ROOT/requirements-dev.txt"
echo "Build environment is ready at $APP_ROOT/.venv"
